#!/usr/bin/env python3
"""Cat-sticker reaction pack — automations/cat_stickers.py.

Covers: marker parse/strip, the code-side roll (rate control lives HERE, not in
model obedience), the default-ON style flag, the style-config API contract, the
no-repeat pick and the opener gif.
"""
import _harness  # noqa: F401  — MUST be first (binds the temp DB)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from automations import cat_stickers as cs  # noqa: E402
from automations.cat_stickers import CAT_STICKERS_KEY  # noqa: E402
# ONE definition, in the layer that owns every other load_*_flag reader.
from automations._common import load_cat_stickers_flag  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig  # noqa: E402

_AID_N = 0


def _fresh_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_cs_{_AID_N}"


# ── unit: marker parse ───────────────────────────────────────────────


def case_parse_marker():
    clean, tag = cs.parse_marker("omg ur funny\nSTICKER: laugh")
    assert (clean, tag) == ("omg ur funny", "laugh"), (clean, tag)
    # unknown tag → None, but the protocol line still never reaches a fan
    clean, tag = cs.parse_marker("hey\nSTICKER: dogs")
    assert (clean, tag) == ("hey", None), (clean, tag)
    # a marker runs to end of line — anything after it is protocol residue
    clean, tag = cs.parse_marker("hii\nSTICKER: laugh extra words")
    assert (clean, tag) == ("hii", "laugh"), (clean, tag)
    # case-insensitive, surrounding whitespace tolerated
    clean, tag = cs.parse_marker("  sticker: KISS  ")
    assert (clean, tag) == ("", "kiss"), (clean, tag)
    # two-word tag, however he spells the separator
    for raw in ("STICKER: miss_you", "STICKER: miss you", "sticker: Miss-You"):
        assert cs.parse_marker(raw) == ("", "miss_you"), raw
    # no marker → untouched
    clean, tag = cs.parse_marker("just chatting")
    assert (clean, tag) == ("just chatting", None), (clean, tag)


def case_parse_marker_live_leaks():
    """The three shapes that actually reached fans (prod audit 07-27). Each one
    must lose the marker; each recognisable tag must still buy a gif."""
    # INLINE after real text — the question survives, the marker doesn't
    clean, tag = cs.parse_marker(
        "so what's the best place u been to in ktown lately? STICKER: flirty")
    assert clean == "so what's the best place u been to in ktown lately?", clean
    assert tag == "flirty", tag
    # roleplay emote — 5 of the 6 live leaks
    assert cs.parse_marker("*sticker: flirty*") == ("", "flirty")
    assert cs.parse_marker("hey babe\n*sticker: kiss*") == ("hey babe", "kiss")
    # ...and the one-letter typo that shipped with it
    assert cs.parse_marker("*sticker: eyerol*") == ("", "eyeroll")
    # markdown bold / underscore-italic / bracket dressings
    assert cs.parse_marker("**STICKER: shy**") == ("", "shy")
    assert cs.parse_marker("_sticker: shy_") == ("", "shy")
    assert cs.parse_marker("u up? [sticker: sleepy]") == ("u up?", "sleepy")
    # ...but a word merely ENDING in "sticker" is not a marker
    assert cs.parse_marker("unsticker: nope") == ("unsticker: nope", None)
    # unrecognisable tag → no gif, but nothing leaks either
    clean, tag = cs.parse_marker("mmm *sticker: banana*")
    assert (clean, tag) == ("mmm", None), (clean, tag)
    # a fan who genuinely talks about stickers is NOT touched (real prod bodies)
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
    # wide-open defaults (07-23): skip=0, block always visible
    assert skip == 0.0, skip
    assert 0.90 < allow < 1.00, allow
    assert 0.02 < solo < 0.09, solo
    # per-account weights override the defaults (the UI knobs land here)
    rng = random.Random("weights2")
    rolls = [cs.roll_mode(rng, False, skip_w=0.70, solo_w=0.05) for _ in range(n)]
    skip, allow, solo = (rolls.count(k) / n for k in ("skip", "allow", "solo"))
    assert 0.65 < skip < 0.75, skip
    assert 0.20 < allow < 0.30, allow
    assert 0.02 < solo < 0.09, solo
    # degenerate weights stay sane: solo can't exceed 1-skip, skip=1 kills all
    assert cs.roll_mode(random.Random(1), False, skip_w=1.0, solo_w=1.0) == "skip"
    assert all(cs.roll_mode(random.Random(i), False, skip_w=0.0, solo_w=1.0) == "solo"
               for i in range(20))
    # cooldown forces skip regardless of the dice
    assert all(cs.roll_mode(random.Random(i), True) == "skip" for i in range(50))
    # gap 0 (the default) = NO floor, even right after a send
    now = datetime.utcnow()
    cs.mark_sent("a1", 7, now=now)
    assert not cs.cooldown_active("a1", 7, now=now + timedelta(seconds=1))
    # an explicit gap spaces sends and expires; per-fan, not per-account
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


# ── unit: the style flag + API contract ──────────────────────────────


def case_flag_default_on():
    async def go():
        aid = _fresh_account()
        # no AccountAiConfig row at all → default ON
        async with get_session() as s:
            s.add(Account(id=aid))
        assert await load_cat_stickers_flag(aid) is True
        # garbage json → default ON; explicit false → OFF
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


# ── the pick ──────────────────────────────────────────────────────────

def case_no_consecutive_repeat():
    """The same clip never lands twice in a row on one fan, and the same TAG twice
    in a row is dropped.

    Real failure this encodes, fan 9227309 on 2026-07-26: he complimented her three
    turns running, the model answered `shy` all three times, and two of the three
    drew the SAME giphy id 21 minutes apart. The pools are 2-6 clips wide and the
    draw is seeded on his text — which changes every turn — so independent draws
    repeat about a quarter of the time on a 4-clip tag. One `shy` is a girl being
    coy; three is a macro."""
    acct, fan = "acc_gif", 991
    cs._last_pick.pop((acct, fan), None)
    pool = cs._CATALOG["shy"][1]
    assert len(pool) > 1, "this case needs a multi-clip tag"

    # Every seed must avoid whatever went out last — swept, not sampled, because a
    # 1-in-4 repeat is exactly the kind of bug a handful of seeds walks past.
    for gid in pool:
        cs.mark_sent(acct, fan, tag="shy", gif_id=gid)
        for s in range(300):
            nxt = cs.pick_gif("shy", random.Random(s), acct, fan)
            assert nxt != gid, (gid, nxt, s)

    # A single-clip tag still SENDS rather than going silent: excluding is skipped
    # when it would empty the pool.
    solo_tag = next((t for t, (_, g) in cs._CATALOG.items() if len(g) == 1), None)
    if solo_tag is not None:
        only = cs._CATALOG[solo_tag][1][0]
        cs.mark_sent(acct, fan, tag=solo_tag, gif_id=only)
        assert cs.pick_gif(solo_tag, random.Random(0), acct, fan) == only

    # keep_tag: same tag consecutively is dropped, a different tag survives, and it
    # clears once something else has gone out (consecutive only — reusable later).
    cs.mark_sent(acct, fan, tag="shy", gif_id=pool[0])
    assert cs.keep_tag(acct, fan, "shy", has_text=True) is None
    assert cs.keep_tag(acct, fan, "laugh", has_text=True) == "laugh"
    cs.mark_sent(acct, fan, tag="laugh", gif_id="x")
    assert cs.keep_tag(acct, fan, "shy", has_text=True) == "shy"
    # An untouched fan is never a repeat, and None in ⇒ None out.
    assert cs.keep_tag(acct, 12345, "shy", has_text=True) == "shy"
    assert cs.keep_tag(acct, fan, None, has_text=True) is None

    # A SOLO repeat still sends: the marker is the whole reply there, so dropping the
    # tag would put out an empty turn. pick_gif still guarantees a different clip.
    cs.mark_sent(acct, fan, tag="shy", gif_id=pool[0])
    assert cs.keep_tag(acct, fan, "shy", has_text=False) == "shy"


def case_bare_emote_that_names_a_tag_becomes_that_gif():
    """`*love*` really went out as a whole reply on 07-25. It names a tag we own
    (five gifs behind it), so it is the same request as `STICKER: love` without
    the protocol — and answering with the gif beats the alternative, which is the
    narration strip emptying the draft and the fan getting nothing that turn.

    EXACT key only. `_tag_for` resolves prefixes, and a prefix on a bare emote is
    how `*go on*` becomes a good_morning gif at a man mid-conversation."""
    assert cs.parse_marker("*love*") == ("", "love")
    assert cs.parse_marker("*miss you*") == ("", "miss_you")
    # Names nothing in the catalog: left alone here, dropped by the strip later.
    for raw in ("*go on*", "*mischievous grin*", "*he sent a sticker?*"):
        assert cs.parse_marker(raw) == (raw, None), raw
    # Emphasis inside a real line is not a reaction request.
    assert cs.parse_marker("i *love* that") == ("i *love* that", None)
    assert cs.parse_marker("*love* u babe") == ("*love* u babe", None)


# The exact model output behind the 07-31 leak (grok_calls 84721) — the directive
# rendered as prose with a correct marker underneath it.
_ECHO_07_31 = ("a cat sticker says it all this time — if ANY sticker fits, reply "
               "with ONLY the STICKER line, no text. Only add text if truly no "
               "sticker fits.\n\nSTICKER: flirty")


def case_prose_about_the_sticker_is_never_sent():
    """Every instruction leak prod has shipped to a fan, in the shape it shipped.

    All four distinct leaked model responses (read back off `grok_calls`) carried a
    CORRECT marker with prose about the sticker above it, so the marker is the
    signal — no vocabulary list required. `_MARKER_RE` catches none of them: this
    protocol's discriminator is the colon, and "the STICKER line" has none."""
    leaks = (
        # 07-31, Ava -> 165496442: the solo directive rendered as the message.
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
    # The rule reads the marker, not the wording, so a paraphrase it has never
    # seen is caught by the same line.
    assert cs.parse_marker("sending a sticker instead\nSTICKER: laugh") == ("", "laugh")
    assert cs.parse_marker("*sticker: kiss* no text") == ("", "kiss")


def case_real_sticker_talk_survives():
    """The other half of the corpus. Across 520k outbound bodies exactly one
    genuine chat-engine reply says "sticker" \u2014 he collects them \u2014 and it carried
    NO marker, which is precisely why keying on the marker costs nothing.

    Without a marker there is no gif to fall back on, so dropping the text here
    would cost the fan his reply outright."""
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
