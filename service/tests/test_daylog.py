#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime  # noqa: E402

from automations import _daylog, _persona, welcome_chatter_for_info  # noqa: E402
from automations import send_followup  # noqa: E402
from automations import _voice  # noqa: E402
from db.models import Fan  # noqa: E402

_AVA_ACTS = {
    "morning_1": "just woke up and made myself a coffee ☕ my dogs are going crazy wanting a walk lol",
    "morning_2": "out with my dogs on the trail — just got back actually 🐕",
    "afternoon_1": "just got back from a little hike, honestly exhausted but in a good way 😅",
    "afternoon_2": "chilling with my pups after a long day outside 🐶",
    "evening": "getting ready to go out country dancing tonight 🤠💃",
    "night": "just got home and hiding under my blankets with the dogs 🐕",
}

_DAY = {
    "date": "2026-08-06", "weekday": "Thursday",
    "beats": [
        {"id": "m1", "slot": "morning_1", "text": "up early, dogs wouldn't let me sleep in"},
        {"id": "m2", "slot": "morning_2", "text": "took the pups up the ridge trail before it got hot"},
        {"id": "a1", "slot": "afternoon_1", "text": "back home, legs are dead but worth it"},
        {"id": "a2", "slot": "afternoon_2", "text": "made a huge iced coffee and did nothing"},
        {"id": "e1", "slot": "evening", "text": "heading out two-steppin later if i can move"},
        {"id": "n1", "slot": "night", "text": "home, boots off, dog on my feet"},
    ],
    "covers": [
        {"id": "c1", "kind": "busy", "text": "sorry, was still out with the dogs"},
        {"id": "c2", "kind": "long", "text": "back — that trail took way longer than i thought"},
    ],
}


def _mk_fan(fan_id: int = 800453746) -> Fan:
    return Fan(account_id="8000149", fan_id=fan_id, of_display_name="Dana",
               occupation="journeyman carpenter",
               hobbies="hiking, exploring, road trips, BBQ, country music, "
                       "volunteering at animal shelter")


def _mk_of_cand(msgs):
    c = welcome_chatter_for_info._Candidate(800453746)
    c.fan_msg_n = sum(1 for d, _ in msgs if d == "in")
    c.last_dir = "in"
    c.last_body = msgs[-1][1]
    c.messages = list(msgs)
    return c


_THREAD = [("in", "How did the world treat my favorite person today?")]



def case_slot_buckets_match_send_followup():
    for h in range(24):
        assert _daylog.slot_index(h) == send_followup._photo_index(h), h
        assert _daylog.slot_key(h) == send_followup._slot_key(h), h
    assert _daylog.SLOT_KEYS == send_followup._SLOT_KEYS


def case_parse_day_log_is_defensive():
    for junk in (None, "", "null", "{", "[]", "[1,2,3]", '{"beats": []}',
                 '{"date": "", "beats": [{"id": "a", "slot": "morning_1", "text": "x"}]}'):
        assert _daylog.parse_day_log(junk) == {}, junk
    partial = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "beats": [{"id": "", "slot": "morning_1", "text": "no id"},
                  {"id": "x", "slot": "brunch", "text": "bad slot"},
                  {"id": "ok", "slot": "evening", "text": "real one"}]}))
    assert [b["id"] for b in partial["beats"]] == ["ok"], partial
    dupe = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "beats": [{"id": "d", "slot": "morning_1", "text": "first"},
                  {"id": "d", "slot": "evening", "text": "second"}]}))
    assert len(dupe["beats"]) == 1, dupe
    assert _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06", "covers": [{"id": "c", "text": "hi"}]})) == {}


def case_covers_nested_inside_beats_are_still_found():
    row = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "beats": [{"id": f"b{i}", "slot": s, "text": f"beat {i}"}
                  for i, s in enumerate(_daylog.SLOT_KEYS)]
        + [{"covers": [{"id": "c1", "kind": "busy", "text": "was out with the dogs"},
                       {"id": "c2", "kind": "long", "text": "just got home"}]}]}))
    assert len(row["beats"]) == len(_daylog.SLOT_KEYS), row["beats"]
    assert [c["id"] for c in row["covers"]] == ["c1", "c2"], row["covers"]
    assert all(b["id"].startswith("b") for b in row["beats"]), row["beats"]
    both = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "covers": [{"id": "top", "text": "top level"}],
        "beats": [{"id": "b1", "slot": "morning_1", "text": "x"},
                  {"covers": [{"id": "nested", "text": "nested"}]}]}))
    assert [c["id"] for c in both["covers"]] == ["top"], both["covers"]


def case_beat_falls_backward_not_forward():
    assert _daylog.beat_for_hour(_DAY, 10)["id"] == "m2"
    assert _daylog.beat_for_hour(_DAY, 19)["id"] == "e1"
    half = {"date": "2026-08-06",
            "beats": [{"id": "m1", "slot": "morning_1", "text": "up early"}]}
    assert _daylog.beat_for_hour(half, 16)["id"] == "m1"
    assert _daylog.beat_for_hour({}, 12) == {}


def case_her_day_turns_over_at_5am_not_midnight():
    tz = -420
    assert _daylog.local_date_str(tz, datetime(2026, 8, 7, 8, 32)) == "2026-08-06"
    assert _daylog.local_date_str(tz, datetime(2026, 8, 7, 11, 32)) == "2026-08-06"
    assert _daylog.local_date_str(tz, datetime(2026, 8, 7, 12, 32)) == "2026-08-07"
    assert _daylog.local_date_str(None, datetime(2026, 8, 7, 12, 32)) == ""
    assert _daylog.is_fresh(_DAY, tz, datetime(2026, 8, 7, 8, 32))
    assert not _daylog.is_fresh(_DAY, tz, datetime(2026, 8, 7, 12, 32))


def case_asks_about_her_day_catches_the_oblique_form():
    dana = "How did the world treat my favorite person today?"
    assert _daylog.asks_about_her_day(dana), "the message that started this must match"
    assert not _persona.asks_about_her(dana), \
        "the bio regex must still NOT match — these cover different classes"
    for yes in ("wyd", "wyd babe", "what are you up to", "whatcha doing rn",
                "hows your day going", "how was your day gorgeous",
                "what did you do today", "how's your evening been",
                "what you been up to", "busy day?", "tell me about your day",
                "qué haces", "cómo estuvo tu día", "que tal tu dia"):
        assert _daylog.asks_about_her_day(yes), yes
    for no in ("", "how old are you", "where do you live", "do you have a boyfriend",
               "i had a long day at work", "you look amazing today",
               "what do you do for work"):
        assert not _daylog.asks_about_her_day(no), no



def _of_prompt(**kw):
    random.seed(1234)
    msgs, _ = welcome_chatter_for_info._build_messages(
        "You are Ava.", _mk_fan(), _mk_of_cand(_THREAD), set(), **kw)
    return msgs[0]["content"], msgs[1]["content"]


_BAN = "don't share your own info unless he asks"
_GIVE = "give a little back"
_MARK = "YOUR DAY SO FAR:"
_REQUIRED = "HE ASKED ABOUT YOUR DAY"


def case_prompt_is_byte_identical_without_a_day_log():
    for build in (_of_prompt,):
        base_sys, base_user = build()
        for kw in ({},
                   {"day": _daylog.Day()},
                   {"day": _daylog.Day({}, 10)},
                   {"day": _daylog.Day(_DAY, None)}):
            sys_c, user_c = build(**kw)
            assert sys_c == base_sys, f"{build.__name__} system drifted with {kw}"
            assert user_c == base_user, f"{build.__name__} user drifted with {kw}"
        assert _BAN in base_sys, "the original ban must survive when she has no day"
        assert _MARK not in base_sys and _GIVE not in base_sys
        assert _REQUIRED not in base_user


def case_day_block_replaces_the_ban_when_a_day_exists():
    for build in (_of_prompt,):
        sys_c, user_c = build(day=_daylog.Day(_DAY, 10))
        assert _MARK in sys_c, f"{build.__name__} lost the day block"
        assert "took the pups up the ridge trail" in sys_c, "wrong slot selected"
        assert _BAN not in sys_c, f"{build.__name__} kept the ban WITH a day log"
        assert _GIVE in sys_c, f"{build.__name__} missing the replacement clause"
        assert _MARK not in user_c
        assert _REQUIRED in user_c, f"{build.__name__} did not require an answer"
        assert _REQUIRED not in sys_c

    quiet = [("in", "you look amazing in your pics")]
    msgs, _ = welcome_chatter_for_info._build_messages(
        "You are Ava.", _mk_fan(), _mk_of_cand(quiet), set(),
        day=_daylog.Day(_DAY, 10))
    assert _MARK in msgs[0]["content"], "the day should still be available"
    assert _REQUIRED not in msgs[1]["content"], "nothing was asked — nothing required"


def case_day_ask_block_only_when_he_asked():
    ask = "hows your day going babe"
    block = _daylog.day_ask_block(_DAY, 10, ask)
    assert "answer FIRST from YOUR DAY SO FAR" in block, block
    assert _daylog.day_ask_block(_DAY, 10, "you're gorgeous") == ""
    assert _daylog.day_ask_block({}, 10, ask) == ""
    assert _daylog.day_ask_block(_DAY, None, ask) == ""


def case_relatable_beat_picks_the_part_he_cares_about():
    day = {"date": "2026-08-06", "beats": [
        {"id": "m1", "slot": "morning_1", "text": "coffee, dogs wouldn't let me sleep",
         "topics": ["dogs", "coffee"]},
        {"id": "m2", "slot": "morning_2", "text": "wandered the old heritage houses downtown",
         "topics": ["architecture", "walking", "town"]},
        {"id": "a1", "slot": "afternoon_1", "text": "finally watched that western everyone raves about",
         "topics": ["movie", "western"]},
        {"id": "e1", "slot": "evening", "text": "pulling my boots on for dance night",
         "topics": ["dancing", "country"]},
    ]}
    carpenter = Fan(account_id="a", fan_id=1,
                    occupation="journeyman carpenter",
                    hobbies="restoring old houses, architecture, woodworking")
    filmbuff = Fan(account_id="a", fan_id=2, hobbies="westerns, classic movies, vinyl")
    nomatch = Fan(account_id="a", fan_id=3, hobbies="scuba diving, chess")

    assert _daylog.relatable_beat(day, 14, carpenter)["id"] == "m2"
    assert _daylog.relatable_beat(day, 14, filmbuff)["id"] == "a1"
    assert _daylog.relatable_beat(day, 14, nomatch) == {}, \
        "no overlap must yield NO bridge — a forced one reads worse than none"
    assert _daylog.relatable_beat(day, 14, None) == {}

    country = Fan(account_id="a", fan_id=4, hobbies="country music, dancing")
    # NEVER a later slot: a plan stated as a thing she did is the one lie this must not tell
    assert _daylog.relatable_beat(day, 14, country) == {}
    assert _daylog.relatable_beat(day, 19, country)["id"] == "e1"

    assert "heritage houses" in _daylog.relatable_block(day, 14, carpenter)
    assert _daylog.relatable_block(day, 14, nomatch) == ""
    assert _daylog.relatable_block(day, None, carpenter) == ""
    assert "ALSO TODAY" not in _daylog.relatable_block(day, 10, carpenter)


def case_overlap_counts_concepts_not_synonyms():
    day = {"date": "2026-08-06", "beats": [
        {"id": "a1", "slot": "afternoon_1",
         "text": "leftover chili hit the spot, now the dogs are passed out",
         "topics": ["lunch", "cooking", "leftovers"]},
        {"id": "n1", "slot": "night",
         "text": "two-stepping at the legion hall, feet are killing me",
         "topics": ["dancing", "country", "bar"]},
    ]}
    dana = Fan(account_id="a", fan_id=800453746,
               occupation="journeyman carpenter",
               hobbies="hiking, BBQ, spicy food, rock music, country music, "
                       "volunteering at animal shelter")
    his = _daylog.fan_interests(dana)
    chili = his & _daylog._words(day["beats"][0]["topics"], day["beats"][0]["text"])
    dance = his & _daylog._words(day["beats"][1]["topics"], day["beats"][1]["text"])
    assert len(chili) > len(dance), "the raw-word bias this guards must still exist"
    assert _daylog._concepts(chili) <= _daylog._concepts(dance), \
        "one interest counts once — a big synonym group is not a better match"
    assert _daylog.relatable_beat(day, 23, dana)["id"] == "n1"
    assert _daylog._concepts(set()) == 0
    assert _daylog._concepts({"kayak", "kayaks"}) == 1


def case_overlap_survives_different_vocabulary():
    day = {"date": "2026-08-06", "beats": [
        {"id": "b1", "slot": "morning_2",
         "text": "took the pups on the old logging trail, they're covered in mud", "topics": []},
        {"id": "b2", "slot": "afternoon_1",
         "text": "cranked skynyrd while scrubbing the kitchen floor", "topics": []},
        {"id": "b3", "slot": "afternoon_2",
         "text": "grabbed fence staples at canadian tire",
         "topics": ["errands", "hardware"]}]}
    hiker = Fan(account_id="a", fan_id=1, hobbies="hiking, exploring")
    rocker = Fan(account_id="a", fan_id=2, hobbies="rock music, country music")
    builder = Fan(account_id="a", fan_id=3, occupation="journeyman carpenter",
                  hobbies="woodworking")
    assert _daylog.relatable_beat(day, 17, hiker)["id"] == "b1", "hiking≠trail"
    assert _daylog.relatable_beat(day, 17, rocker)["id"] == "b2", "rock≠skynyrd"
    assert _daylog.relatable_beat(day, 17, builder)["id"] == "b3", "carpenter≠hardware"
    assert _daylog.relatable_beat(day, 17, Fan(account_id="a", fan_id=4,
                                               hobbies="scuba diving")) == {}
    assert _daylog._topics(["fishing", "lake"]) == ["fishing", "lake"]
    assert _daylog._topics("fishing, lake") == ["fishing", "lake"]
    assert _daylog._topics("errand fishing") == ["errand fishing"]
    assert _daylog._topics(None) == [] and _daylog._topics(7) == []


def case_male_lane_gets_its_own_day_rule():
    hers = _daylog.day_block(_DAY, 10, _voice.VOICE_HER)
    his = _daylog.day_block(_DAY, 10, _voice.VOICE_HIM)
    assert hers and his and hers != his
    assert "not an invitation" in his, "male lane lost its register clause"
    assert "not an invitation" not in hers
    assert _daylog.day_block(_DAY, 10) == hers
    assert _daylog.day_block({}, 10, _voice.VOICE_HIM) == ""


_harness.run()


def case_load_day_reads_the_brain_row_once():
    import asyncio

    calls: list[str] = []

    class _Row:
        style_config_json = json.dumps({_daylog.DAY_LOG_ENABLED_KEY: True})

    async def _fake_fetch(account_id):
        calls.append(account_id)
        return _Row()

    async def _fake_ensure(account_id, cfg_row, **kw):
        assert cfg_row is not None, "the row must be handed on, not re-fetched"
        return _DAY

    orig_fetch, orig_ensure = _daylog._load_cfg_row, _daylog.ensure_day_log
    _daylog._load_cfg_row, _daylog.ensure_day_log = _fake_fetch, _fake_ensure
    try:
        day = asyncio.run(_daylog.load_day(
            "acct", _Row(), model="m", purpose="p", clock_tz=0,
            now=datetime(2026, 8, 6, 10, 0)))
        assert calls == [], f"row re-fetched despite being passed: {calls}"
        assert day and day.hour == 10 and day.log is _DAY

        day = asyncio.run(_daylog.load_day(
            "acct", model="m", purpose="p", clock_tz=0,
            now=datetime(2026, 8, 6, 10, 0)))
        assert calls == ["acct"], f"expected exactly one row read, got {calls}"
        assert day

        class _Off:
            style_config_json = json.dumps({_daylog.DAY_LOG_ENABLED_KEY: False})

        async def _boom(*a, **k):
            raise AssertionError("ensure_day_log ran with the flag off")

        _daylog.ensure_day_log = _boom
        off = asyncio.run(_daylog.load_day("acct", _Off(), model="m", purpose="p",
                                           clock_tz=0))
        assert not off and off.log == {} and off.hour is None
        assert off.system_block(_voice.HER) == ""
        assert off.user_block(_mk_fan(), "wyd") == ""
        assert off.date == ""
    finally:
        _daylog._load_cfg_row, _daylog.ensure_day_log = orig_fetch, orig_ensure
