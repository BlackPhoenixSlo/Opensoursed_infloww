#!/usr/bin/env python3
"""test_daylog.py — the creator's DAY reaches the chat prompt, and nothing else moves.

Root incident (2026-08-05, fan 800453746 "Dana", $1,301.45 on account 8000149): he
wrote "How did the world treat my favorite person today?" and got five bubbles
containing no fact, feeling or event of hers, then a pivot to his job 55s later.
Measured on prod the next day: 26 of 2,232 outbound chat TURNS (1.17%) over 7 days
said anything about her own life. Her account had held the answer the whole time —
`time_activities_json` says she walks dogs on trails and goes country dancing, and
his profile says he hikes, volunteers at an animal shelter and likes country music.
No chat engine had ever read that column.

  case_slot_buckets_match_send_followup:
      the 6 time-of-day buckets are byte-identical to send_followup's for all 24
      hours — if they drifted, the welcome message and the chat engine would put
      her in two different places at the same moment.
  case_parse_day_log_is_defensive:
      NULL / garbage / a stored list / a beat with no id / an unknown slot all
      collapse to {} or are dropped, never raise. This parses on a send path.
  case_beat_falls_backward_not_forward:
      a half-generated day degrades to a stale-but-TRUE earlier beat, never to a
      claim about a future she has not lived yet.
  case_asks_about_her_day_catches_the_oblique_form:
      the message that started this ("How did the world treat my favorite person
      today?") must match, and _persona's bio-question regex must still NOT — the
      two detectors cover different classes and the gap between them was the bug.
  case_prompt_is_byte_identical_without_a_day_log:
      THE SAFETY CASE. The engine's builder, with no day log, produces a prompt
      byte-for-byte equal to the one that ships today — including the original
      "don't share your own info unless he asks" clause.
  case_day_block_replaces_the_ban_when_a_day_exists:
      and with a day log: the ban is gone, YOUR DAY SO FAR is in the SYSTEM half,
      and the required-answer line is in the USER half only when he actually asked.
  case_day_ask_block_only_when_he_asked:
      the answer-him line renders only when he asked, a day exists and the hour
      is known.
  case_male_lane_gets_its_own_day_rule:
      the block is laned; her prompt is byte-identical to the un-laned original.
  case_load_day_reads_the_brain_row_once:
      the flag, the persona, the timezone and the day are all columns of ONE row.
      Both engines used to check the flag through its own by-id loader and then
      fetch the row again, so every sweep paid two queries for one row on every
      account — including the ones the feature is off for.

Run: ./venv/bin/python service/tests/test_daylog.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime  # noqa: E402

from automations import _daylog, _persona, welcome_chatter_for_info  # noqa: E402
from automations import send_followup  # noqa: E402
from automations import _voice  # noqa: E402
from db.models import Fan  # noqa: E402

# Ava's real prod slots (account 8000149), verbatim — the tone seed.
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


# ── the pure helpers ──────────────────────────────────────────────────

def case_slot_buckets_match_send_followup():
    for h in range(24):
        assert _daylog.slot_index(h) == send_followup._photo_index(h), h
        assert _daylog.slot_key(h) == send_followup._slot_key(h), h
    assert _daylog.SLOT_KEYS == send_followup._SLOT_KEYS


def case_parse_day_log_is_defensive():
    for junk in (None, "", "null", "{", "[]", "[1,2,3]", '{"beats": []}',
                 '{"date": "", "beats": [{"id": "a", "slot": "morning_1", "text": "x"}]}'):
        assert _daylog.parse_day_log(junk) == {}, junk
    # A beat with no id can never be deduped; an unknown slot can never be selected.
    # Either one would silently become a line she repeats forever, so both drop.
    partial = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "beats": [{"id": "", "slot": "morning_1", "text": "no id"},
                  {"id": "x", "slot": "brunch", "text": "bad slot"},
                  {"id": "ok", "slot": "evening", "text": "real one"}]}))
    assert [b["id"] for b in partial["beats"]] == ["ok"], partial
    # Duplicate ids collapse — two beats sharing an id would burn both at once.
    dupe = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "beats": [{"id": "d", "slot": "morning_1", "text": "first"},
                  {"id": "d", "slot": "evening", "text": "second"}]}))
    assert len(dupe["beats"]) == 1, dupe
    # Covers alone are not a day.
    assert _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06", "covers": [{"id": "c", "text": "hi"}]})) == {}


def case_covers_nested_inside_beats_are_still_found():
    """The shape prod's very first generated day actually came back in.

    Asked for `{"beats": [...], "covers": [...]}` the model appended the covers as a
    SEVENTH element of `beats` — past the `_MAX_BEATS` slice, so the beat loop never
    saw it and all three covers were dropped silently. Nothing was malformed enough
    to notice: six good beats and an empty cover list."""
    row = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "beats": [{"id": f"b{i}", "slot": s, "text": f"beat {i}"}
                  for i, s in enumerate(_daylog.SLOT_KEYS)]
        + [{"covers": [{"id": "c1", "kind": "busy", "text": "was out with the dogs"},
                       {"id": "c2", "kind": "long", "text": "just got home"}]}]}))
    assert len(row["beats"]) == len(_daylog.SLOT_KEYS), row["beats"]
    assert [c["id"] for c in row["covers"]] == ["c1", "c2"], row["covers"]
    # The wrapper is not itself a beat — it has no slot and no text.
    assert all(b["id"].startswith("b") for b in row["beats"]), row["beats"]
    # A well-formed top-level list still wins over anything nested.
    both = _daylog.parse_day_log(json.dumps({
        "date": "2026-08-06",
        "covers": [{"id": "top", "text": "top level"}],
        "beats": [{"id": "b1", "slot": "morning_1", "text": "x"},
                  {"covers": [{"id": "nested", "text": "nested"}]}]}))
    assert [c["id"] for c in both["covers"]] == ["top"], both["covers"]


def case_beat_falls_backward_not_forward():
    assert _daylog.beat_for_hour(_DAY, 10)["id"] == "m2"
    assert _daylog.beat_for_hour(_DAY, 19)["id"] == "e1"
    # A day that only generated its morning: 4pm must read the MORNING beat (she
    # did do that) rather than the evening's (a claim about a future she has not
    # reached). Forward-fill here would have her "heading out two-steppin" at 4pm.
    half = {"date": "2026-08-06",
            "beats": [{"id": "m1", "slot": "morning_1", "text": "up early"}]}
    assert _daylog.beat_for_hour(half, 16)["id"] == "m1"
    assert _daylog.beat_for_hour({}, 12) == {}


def case_her_day_turns_over_at_5am_not_midnight():
    """The `night` slot runs 9pm THROUGH 5am, so the DATE has to span midnight too.

    On a midnight boundary a fan messaging at 2am rolls her onto a brand-new day and
    reads its `night` beat — an evening she has not lived yet. That is the one slot
    most likely to be active during insomnia hours and it would be guaranteed wrong."""
    tz = -420                                      # America/Vancouver, PDT
    # 08:32 UTC = 01:32 local on the 7th — still the SIXTH's day for her.
    assert _daylog.local_date_str(tz, datetime(2026, 8, 7, 8, 32)) == "2026-08-06"
    # 11:32 UTC = 04:32 local, still the sixth.
    assert _daylog.local_date_str(tz, datetime(2026, 8, 7, 11, 32)) == "2026-08-06"
    # 12:32 UTC = 05:32 local — NOW it is the seventh.
    assert _daylog.local_date_str(tz, datetime(2026, 8, 7, 12, 32)) == "2026-08-07"
    assert _daylog.local_date_str(None, datetime(2026, 8, 7, 12, 32)) == ""
    # And a row dated for the sixth is still FRESH at 1:32am on the seventh — the
    # freshness check and the stamp must use the same boundary or every turn between
    # midnight and 5am regenerates the day (17 accounts × one call per turn).
    assert _daylog.is_fresh(_DAY, tz, datetime(2026, 8, 7, 8, 32))
    assert not _daylog.is_fresh(_DAY, tz, datetime(2026, 8, 7, 12, 32))


def case_asks_about_her_day_catches_the_oblique_form():
    # THE message. It matches none of _persona's bio patterns, which is why the
    # whole persona machinery was blind to this class.
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


# ── the safety case ───────────────────────────────────────────────────

def _of_prompt(**kw):
    # SEEDED: the builder picks its STYLE FOR THIS MESSAGE with random.choice, so
    # two unseeded calls differ in a line that has nothing to do with the day log.
    # Without this the byte-identical assertion below fails on style drift and hides
    # whatever it was actually meant to catch.
    random.seed(1234)
    msgs, _ = welcome_chatter_for_info._build_messages(
        "You are Ava.", _mk_fan(), _mk_of_cand(_THREAD), set(), **kw)
    return msgs[0]["content"], msgs[1]["content"]


_BAN = "don't share your own info unless he asks"
_GIVE = "give a little back"
_MARK = "YOUR DAY SO FAR:"
_REQUIRED = "HE ASKED ABOUT YOUR DAY"


def case_prompt_is_byte_identical_without_a_day_log():
    """The whole safety argument. An account with the feature off, or with no day
    generated yet, must send the prompt that ships today — not a similar one."""
    for build in (_of_prompt,):
        base_sys, base_user = build()
        # Explicit "absent" and the flag-off shape both equal the default.
        for kw in ({},                                   # the parameter default
                   {"day": _daylog.Day()},               # the flag-off shape
                   {"day": _daylog.Day({}, 10)},         # hour but no day
                   # A day present but no hour (no tz) must ALSO render nothing:
                   # the hour is what selects the beat, and guessing it would put
                   # her on a trail at 3am.
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
        # The day is account-constant ⇒ SYSTEM half (prefix-cached across fans).
        assert _MARK not in user_c
        # He asked, so the required line fires — and only in the per-fan half.
        assert _REQUIRED in user_c, f"{build.__name__} did not require an answer"
        assert _REQUIRED not in sys_c

    # He did NOT ask ⇒ the day is still offered, but nothing is required.
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
    # Not asked / no day / no hour ⇒ nothing to answer.
    assert _daylog.day_ask_block(_DAY, 10, "you're gorgeous") == ""
    assert _daylog.day_ask_block({}, 10, ask) == ""
    assert _daylog.day_ask_block(_DAY, None, ask) == ""


def case_relatable_beat_picks_the_part_he_cares_about():
    """The bridge is a SELECTION, not a hope.

    First build asked the model to connect her one current activity to his whole
    profile — which lands ~3 times in 10 and cannot land at all when the two have
    nothing in common. The day now spans domains and the code picks the overlapping
    part, so 'he likes architecture' meets 'walked the heritage houses' by matching
    rather than by luck."""
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

    # Same day, same hour, three fans — three different true things.
    assert _daylog.relatable_beat(day, 14, carpenter)["id"] == "m2"
    assert _daylog.relatable_beat(day, 14, filmbuff)["id"] == "a1"
    assert _daylog.relatable_beat(day, 14, nomatch) == {}, \
        "no overlap must yield NO bridge — a forced one reads worse than none"
    assert _daylog.relatable_beat(day, 14, None) == {}

    # NEVER a later slot: at 2pm "pulling my boots on for dance night" has not
    # happened, and stating a plan as a thing she did is the one lie this must not
    # tell. A country-music fan gets nothing at 2pm and the dance beat at 7pm.
    country = Fan(account_id="a", fan_id=4, hobbies="country music, dancing")
    assert _daylog.relatable_beat(day, 14, country) == {}
    assert _daylog.relatable_beat(day, 19, country)["id"] == "e1"

    # The block renders per-fan and is EMPTY for the fan with no overlap.
    assert "heritage houses" in _daylog.relatable_block(day, 14, carpenter)
    assert _daylog.relatable_block(day, 14, nomatch) == ""
    assert _daylog.relatable_block(day, None, carpenter) == ""
    # When the overlap IS what she's doing right now, don't print it twice.
    assert "ALSO TODAY" not in _daylog.relatable_block(day, 10, carpenter)


def case_overlap_counts_concepts_not_synonyms():
    """Prod's first real day, and the reason the bridge froze on the wrong beat.

    Scoring the raw word overlap scores the SIZE OF THE SYNONYM GROUP: `cooking`
    expands to bake/barbecue/bbq/grill/kitchen/recipe, so a lunchtime "leftover
    chili" out-scored "two-stepping at the legion hall" 20 words to 14 against a fan
    whose profile literally says country music — and, being the high scorer, held
    the bridge for the whole evening. One shared interest must count once however
    many words the table happens to spell it with."""
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
    # …so by night the bridge is the dancing, not the leftovers.
    assert _daylog.relatable_beat(day, 23, dana)["id"] == "n1"
    # A word outside the table is still its own concept, not free score.
    assert _daylog._concepts(set()) == 0
    assert _daylog._concepts({"kayak", "kayaks"}) == 1


def case_overlap_survives_different_vocabulary():
    """His profile and her day name the same thing differently.

    Fans write "hiking"; the generator writes "trail". Her canon says "Southern
    Rock"; a beat says "skynyrd". Literal word matching found neither, which is most
    of why the first build bridged ~3 times in 10. A flat synonym table is the right
    tool here (unlike pins v2, where a lexicon kept 0 of 83) because BOTH failure
    directions are cheap: a miss just means she doesn't mention that part of her day,
    and a false hit surfaces a true thing to a fan who may not care."""
    day = {"date": "2026-08-06", "beats": [
        {"id": "b1", "slot": "morning_2",
         "text": "took the pups on the old logging trail, they're covered in mud", "topics": []},
        {"id": "b2", "slot": "afternoon_1",
         "text": "cranked skynyrd while scrubbing the kitchen floor", "topics": []},
        # Tags carry the domain when the prose doesn't name it — verbatim from a
        # real generated day, where the text says "canadian tire" and only the tag
        # says "hardware".
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
    # Still no forced bridge for a fan who genuinely shares nothing.
    assert _daylog.relatable_beat(day, 17, Fan(account_id="a", fan_id=4,
                                               hobbies="scuba diving")) == {}
    # Tag shapes the model actually returns on different days all parse.
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
    # Default (no voice passed) is hers, byte-for-byte — a caller that predates the
    # lane must not silently get male copy.
    assert _daylog.day_block(_DAY, 10) == hers
    assert _daylog.day_block({}, 10, _voice.VOICE_HIM) == ""


_harness.run()


def case_load_day_reads_the_brain_row_once():
    """One row holds the flag, the persona, the tz and the day — so read it once.

    Both engines used to ask `load_enabled(account_id)` (its own `s.get`) and then
    hand `ensure_day_log` the row, which is two queries for one row on every account
    every sweep — paid even by the accounts the feature is OFF for, which is most of
    them. `load_day` is the one entry point, and it takes the row the caller already
    holds when there is one."""
    import asyncio

    calls: list[str] = []

    class _Row:                       # the brain row, flag ON
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
        # A caller that already holds the row: NOTHING is fetched.
        day = asyncio.run(_daylog.load_day(
            "acct", _Row(), model="m", purpose="p", clock_tz=0,
            now=datetime(2026, 8, 6, 10, 0)))
        assert calls == [], f"row re-fetched despite being passed: {calls}"
        assert day and day.hour == 10 and day.log is _DAY

        # welcome_chatter_for_info's shape: it holds no row, so exactly ONE fetch — never two.
        day = asyncio.run(_daylog.load_day(
            "acct", model="m", purpose="p", clock_tz=0,
            now=datetime(2026, 8, 6, 10, 0)))
        assert calls == ["acct"], f"expected exactly one row read, got {calls}"
        assert day

        # Flag OFF ⇒ the empty Day, and the generator is never even reached.
        class _Off:
            style_config_json = json.dumps({_daylog.DAY_LOG_ENABLED_KEY: False})

        async def _boom(*a, **k):
            raise AssertionError("ensure_day_log ran with the flag off")

        _daylog.ensure_day_log = _boom
        off = asyncio.run(_daylog.load_day("acct", _Off(), model="m", purpose="p",
                                           clock_tz=0))
        assert not off and off.log == {} and off.hour is None
        # …and the empty Day renders nothing at all — the OFF-path guarantee lives
        # on the type, not on each caller remembering to branch.
        assert off.system_block(_voice.HER) == ""
        assert off.user_block(_mk_fan(), "wyd") == ""
        assert off.date == ""
    finally:
        _daylog._load_cfg_row, _daylog.ensure_day_log = orig_fetch, orig_ensure
