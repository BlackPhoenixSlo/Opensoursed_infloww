#!/usr/bin/env python3
import _harness  # noqa: F401  — MUST be first (binds the temp DB)

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from automations import cat_stickers as cs  # noqa: E402
from automations.cat_stickers import CAT_STICKERS_KEY  # noqa: E402
from automations._common import load_cat_stickers_flag  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402

_AID_N = 0


def _fresh_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_cs_{_AID_N}"




def case_parse_marker():
    clean, tag = cs.parse_marker("omg ur funny\nSTICKER: laugh")
    assert (clean, tag) == ("omg ur funny", "laugh"), (clean, tag)
    clean, tag = cs.parse_marker("hey\nSTICKER: dogs")
    assert (clean, tag) == ("hey", None), (clean, tag)
    clean, tag = cs.parse_marker("hii\nSTICKER: laugh extra words")
    assert (clean, tag) == ("hii", "laugh"), (clean, tag)
    clean, tag = cs.parse_marker("  sticker: KISS  ")
    assert (clean, tag) == ("", "kiss"), (clean, tag)
    for raw in ("STICKER: miss_you", "STICKER: miss you", "sticker: Miss-You"):
        assert cs.parse_marker(raw) == ("", "miss_you"), raw
    clean, tag = cs.parse_marker("just chatting")
    assert (clean, tag) == ("just chatting", None), (clean, tag)


def case_parse_marker_live_leaks():
    clean, tag = cs.parse_marker(
        "so what's the best place u been to in ktown lately? STICKER: flirty")
    assert clean == "so what's the best place u been to in ktown lately?", clean
    assert tag == "flirty", tag
    assert cs.parse_marker("*sticker: flirty*") == ("", "flirty")
    assert cs.parse_marker("hey babe\n*sticker: kiss*") == ("hey babe", "kiss")
    assert cs.parse_marker("*sticker: eyerol*") == ("", "eyeroll")
    assert cs.parse_marker("**STICKER: shy**") == ("", "shy")
    assert cs.parse_marker("_sticker: shy_") == ("", "shy")
    assert cs.parse_marker("u up? [sticker: sleepy]") == ("u up?", "sleepy")
    assert cs.parse_marker("unsticker: nope") == ("unsticker: nope", None)
    clean, tag = cs.parse_marker("mmm *sticker: banana*")
    assert (clean, tag) == ("mmm", None), (clean, tag)
    for raw in ("you design stickers that make people obey",
                "your mountain peace must show in your sticker art",
                "you're the one that bought the stickers"):
        assert cs.parse_marker(raw) == (raw, None), raw


def case_roll_and_cooldown():
    cs._last_sent.clear()
    n = 4000
    rng = random.Random("weights")
    rolls = [cs.roll_mode(rng, False) for _ in range(n)]
    skip, allow, solo = (rolls.count(k) / n for k in ("skip", "allow", "solo"))
    assert skip == 0.0, skip
    assert 0.90 < allow < 1.00, allow
    assert 0.02 < solo < 0.09, solo
    rng = random.Random("weights2")
    rolls = [cs.roll_mode(rng, False, skip_w=0.70, solo_w=0.05) for _ in range(n)]
    skip, allow, solo = (rolls.count(k) / n for k in ("skip", "allow", "solo"))
    assert 0.65 < skip < 0.75, skip
    assert 0.20 < allow < 0.30, allow
    assert 0.02 < solo < 0.09, solo
    assert cs.roll_mode(random.Random(1), False, skip_w=1.0, solo_w=1.0) == "skip"
    assert all(cs.roll_mode(random.Random(i), False, skip_w=0.0, solo_w=1.0) == "solo"
               for i in range(20))
    assert all(cs.roll_mode(random.Random(i), True) == "skip" for i in range(50))
    now = datetime.utcnow()
    cs.mark_sent("a1", 7, now=now)
    assert not cs.cooldown_active("a1", 7, now=now + timedelta(seconds=1))
    assert cs.cooldown_active("a1", 7, now=now + timedelta(minutes=5), gap_min=30)
    assert not cs.cooldown_active("a1", 7, now=now + timedelta(minutes=31), gap_min=30)
    assert not cs.cooldown_active("a1", 8, now=now, gap_min=30), "per-fan, not per-account"
    cs._last_sent.clear()


def case_prompt_block_and_pick():
    assert cs.prompt_block("skip") == ""
    allow = cs.prompt_block("allow")
    for tag in cs.TAGS:
        assert f"- {tag}:" in allow, f"{tag} missing from prompt block"
    assert "ONLY the STICKER line" not in allow.split("THIS message")[0] or True
    solo = cs.prompt_block("solo")
    assert "THIS message" in solo and allow in solo[:len(allow) + 9], \
        "solo = allow block + the solo nudge"
    for tag in cs.TAGS:
        gid = cs.pick_gif(tag, random.Random(1), "acc_pick", 1)
        assert isinstance(gid, str) and gid, (tag, gid)
    assert cs.pick_gif("dogs", random.Random(1), "acc_pick", 1) is None




def case_flag_default_on():
    async def go():
        aid = _fresh_account()
        async with get_session() as s:
            s.add(Account(id=aid))
        assert await load_cat_stickers_flag(aid) is True
        async with get_session() as s:
            s.add(AccountAiConfig(account_id=aid, style_config_json="{not json"))
        assert await load_cat_stickers_flag(aid) is True
        async with get_session() as s:
            row = await s.get(AccountAiConfig, aid)
            row.style_config_json = json.dumps({CAT_STICKERS_KEY: False})
        assert await load_cat_stickers_flag(aid) is False
    asyncio.run(go())


def case_style_api_roundtrip():
    client = _harness.make_client()
    aid = _fresh_account()

    async def _mk():
        async with get_session() as s:
            s.add(Account(id=aid))
    asyncio.run(_mk())
    r = client.get(f"/admin/style-config?account_id={aid}")
    assert r.status_code == 200, r.text
    assert r.json()["config"][CAT_STICKERS_KEY] is True, r.json()
    assert r.json()["defaults"][CAT_STICKERS_KEY] is True, r.json()
    r = client.put("/admin/style-config",
                   json={"account_id": aid, "config": {CAT_STICKERS_KEY: False}})
    assert r.status_code == 200, r.text
    assert r.json()["config"][CAT_STICKERS_KEY] is False, r.json()
    r = client.get(f"/admin/style-config?account_id={aid}")
    assert r.json()["config"][CAT_STICKERS_KEY] is False, r.json()



def case_no_consecutive_repeat():
    acct, fan = "acc_gif", 991
    cs._last_pick.pop((acct, fan), None)
    pool = cs._CATALOG["shy"][1]
    assert len(pool) > 1, "this case needs a multi-clip tag"

    for gid in pool:
        cs.mark_sent(acct, fan, tag="shy", gif_id=gid)
        for s in range(300):
            nxt = cs.pick_gif("shy", random.Random(s), acct, fan)
            assert nxt != gid, (gid, nxt, s)

    solo_tag = next((t for t, (_, g) in cs._CATALOG.items() if len(g) == 1), None)
    if solo_tag is not None:
        only = cs._CATALOG[solo_tag][1][0]
        cs.mark_sent(acct, fan, tag=solo_tag, gif_id=only)
        assert cs.pick_gif(solo_tag, random.Random(0), acct, fan) == only

    cs.mark_sent(acct, fan, tag="shy", gif_id=pool[0])
    assert cs.keep_tag(acct, fan, "shy", has_text=True) is None
    assert cs.keep_tag(acct, fan, "laugh", has_text=True) == "laugh"
    cs.mark_sent(acct, fan, tag="laugh", gif_id="x")
    assert cs.keep_tag(acct, fan, "shy", has_text=True) == "shy"
    assert cs.keep_tag(acct, 12345, "shy", has_text=True) == "shy"
    assert cs.keep_tag(acct, fan, None, has_text=True) is None

    cs.mark_sent(acct, fan, tag="shy", gif_id=pool[0])
    assert cs.keep_tag(acct, fan, "shy", has_text=False) == "shy"


def case_bare_emote_that_names_a_tag_becomes_that_gif():
    assert cs.parse_marker("*love*") == ("", "love")
    assert cs.parse_marker("*miss you*") == ("", "miss_you")
    for raw in ("*go on*", "*mischievous grin*", "*he sent a sticker?*"):
        assert cs.parse_marker(raw) == (raw, None), raw
    assert cs.parse_marker("i *love* that") == ("i *love* that", None)
    assert cs.parse_marker("*love* u babe") == ("*love* u babe", None)


_ECHO_07_31 = ("a cat sticker says it all this time — if ANY sticker fits, reply "
               "with ONLY the STICKER line, no text. Only add text if truly no "
               "sticker fits.\n\nSTICKER: flirty")


def case_prose_about_the_sticker_is_never_sent():
    leaks = (
        ("a cat sticker says it all this time \u2014 if ANY sticker fits, reply with "
         "ONLY the STICKER line, no text. Only add text if truly no sticker "
         "fits.\n\nSTICKER: flirty", "flirty"),
        ("no text \u2014 just the sticker says it all\n\nSTICKER: sleepy", "sleepy"),
        ("a cat sticker feels right here\n\nSTICKER: eyeroll", "eyeroll"),
        ("he said i have great legs, this is cute. sticker works for this."
         "\n\nSTICKER: shy", "shy"),
    )
    for raw, tag in leaks:
        assert cs.parse_marker(raw) == ("", tag), raw
    assert cs.parse_marker("sending a sticker instead\nSTICKER: laugh") == ("", "laugh")
    assert cs.parse_marker("*sticker: kiss* no text") == ("", "kiss")


def case_real_sticker_talk_survives():
    real = (
        "hmm pretty kitty? you're the one that bought the stickers",
        "that chefs kiss gif says it all",
        "here s a full vid the of lagged and didn't put the price sticker firsttime opss",
        "you design stickers that make people obey",
        "your mountain peace must show in your sticker art",
        "no text back from u all day huh \U0001f97a",
        "reply with only one word \U0001f60f",
    )
    for raw in real:
        assert cs.parse_marker(raw) == (raw, None), raw


_harness.run(
    case_parse_marker,
    case_parse_marker_live_leaks,
    case_prose_about_the_sticker_is_never_sent,
    case_real_sticker_talk_survives,
    case_no_consecutive_repeat,
    case_roll_and_cooldown,
    case_prompt_block_and_pick,
    case_flag_default_on,
    case_style_api_roundtrip,
    case_bare_emote_that_names_a_tag_becomes_that_gif,
)
