"""Inbound intent detectors (content ask, escalation, heat) + content_payer_fans."""
from __future__ import annotations

import re

from db.engine import get_session
from db.models import Message, Transaction
from sqlalchemy import and_, or_, select


# ── "Fan asked to see content via text" → natural tip-ask ─────────────
# When a fan asks to SEE content in a plain text ("can i see some content??",
# "show me more", "what u got"), the info-gather / keep-warm senders (welcome_chatter_for_info,
# autoreply) don't sell PPV — but answering with banter ignores a buying signal,
# and the old never-sell fallback literally blurted the bare word "tip". So those
# senders swap in a natural, in-voice tip-ask ("tip me $X and i'll send u something
# 😏") — NEVER the bare word "tip". Nothing sends media for the tip
# automatically: the tip_reward automation was removed.
#
# Two natural ways to tip (the model picks whichever flows): a $amount tip right
# here in chat, OR a tip under a feed post/pic he likes. A post tip lands in chat
# as a tip message too, so it routes through the SAME on_inbound_tip path — and
# it doubles as a signal of what he's into.
#
# ── Text normalisation. READ THIS BEFORE TOUCHING ANY PATTERN BELOW. ─────────────
#
# Phone keyboards autocorrect ' into ’ (U+2019, RIGHT SINGLE QUOTATION MARK). 14.4% of
# real inbound messages on prod carry one. Every pattern in this file
# spells contractions with a STRAIGHT apostrophe (`can'?t`, `i'?m`, `what'?s`), and a
# curly one does not match it. So:
#
#     "Sorry can't afford to buy content"  → decline=soft, regret=True   ✅
#     "Sorry can’t afford to buy content"  → decline=None, regret=False  ❌
#
# The second is what a man actually types. The poverty brake, the decline classifier and
# the buying-signal detectors were all silently blind to him — which means the seller
# would put a FRESH PRICE in front of a man who had just said he was broke. That is the
# worst thing this system can do, and it was one character wide.
#
# Normalise at every detector entry point (defence in depth — these are pure functions
# called from several places), never by asking each pattern to spell both forms.
_SMART_PUNCT = str.maketrans({
    "’": "'", "‘": "'", "‛": "'", "′": "'", "`": "'",
    # ʼ U+02BC (several Android keyboards + copy-paste from non-English sources) and
    # ＇ U+FF07 (fullwidth/CJK IMEs) reproduce the SAME failure as U+2019: "can ʼ t
    # afford" matched nothing, so a broke man got re-priced. Fold every apostrophe
    # variant a phone can emit, not just the famous one.
    "ʼ": "'", "＇": "'", "՚": "'", "ꞌ": "'", "᾿": "'",
    "“": '"', "”": '"',
    "–": "-", "—": "-",
})


def norm_text(text: str | None) -> str:
    """Fold smart punctuation to ASCII so the detectors see what he meant to type."""
    return (text or "").translate(_SMART_PUNCT)


# CONTENT_ASK_RE is the canonical content-ask detector. Code-side, not model judgment — when he's begging to
# buy, the gather goal yields. Extended over the original to also catch the
# "(can i) see (some) content/pics/..." family the original missed.
CONTENT_ASK_RE = re.compile(
    r"(what else|what'?s next|whats next|show me|send (me |it |smth |something )"
    r"|got (any|anything)|anything (spicy|hot|else|for (me|us))|gimme|"
    r"i want (more|it|some)|more (pics|vids|photos|videos|content)|next one|"
    r"what (else )?(do|did) (u|you) (have|got|film)|unlock|spoil (u|you)|"
    r"in the mood|what (u|you) got"
    r"|can i see|lemme see|let me see|wanna see|want to see"
    # Real corpus (fans who then PAID $25-$45): the ask is rarely the tidy "wanna see".
    # "I would like to see how you touch your pussy" and "Any videos of you getting
    # fucked?" were both invisible to the patterns above.
    r"|(would |i'?d )?(like|love) to see|dying to see|need to see|"
    r"any (pics?|vids?|videos?|photos?|nudes?|content)|"
    r"(send|show|do) (u|you) have|"
    # Recall (2026-07-15 audit): "send nudes" / "i want nudes" — the most iconic buy
    # signal on the platform — matched neither branch. `nudes` has no innocent reading.
    r"(send|want|get|gimme|got any) (me |some |ur |your )?nudes?\b|"
    # 🚨 The SUBJECT sits between the verb and the media word, and the fixed
    # option list could not hold it. Measured live 2026-08-12: "Do you send ass
    # pics?" matched NOTHING here, so the turn was never a content_ask, the ask
    # lane never armed, and the model answered a named request with a blind
    # catalog pick. `\w+ ` for the noun he actually named; "do (u|you) send/sell"
    # for the question form, which is how a fan asks before he asks.
    r"(do|d) ?(u|you|ya) (send|sell)\b|"
    r"send (me |ur |your |some )?(\w+ )?(pics?|vids?|videos?|photos?|content)\b|"
    # NOT a bare `see (how|what|you|u|it)`. That matched "see you later babe" — the most
    # common sign-off on the platform — plus "i see what you mean" and "see you
    # tomorrow". Two goodbyes in a 6-message window were enough to make thread_heat()
    # return True, so with force_ask on a fan would have been sent a PPV for saying
    # goodnight. It added no recall the branches above don't already have: "i would like
    # to see how you touch your pussy" is caught by `(would |i'?d )?(like|love) to see`.
    r"i (want|need) (to see|you to)"
    r"|see (some |the |ur |your |more |any )?"
    r"(content|pics?|photos?|vids?|videos?|nudes?|something))",
    re.IGNORECASE)


def is_content_ask(text: str | None) -> bool:
    """True when the fan's message is explicitly asking to SEE content (the buying
    signal CONTENT_ASK_RE detects). Empty/None → False."""
    return bool(text) and bool(CONTENT_ASK_RE.search(norm_text(text)))


# ESCALATION_RE — closer-ONLY buying-adjacent signal. A fan getting physical /
# horny ("can i spank it", "wanna play", "so hard") is a HOT moment, even though it's not an explicit "show me content"
# ask. Kept SEPARATE from CONTENT_ASK_RE on purpose: CONTENT_ASK_RE also drives
# welcome_chatter_for_info's and autoreply's tip-ask, and we do NOT want the opener pitching
# mid-gather — only the closer's intent gate consults this.
ESCALATION_RE = re.compile(
    r"(spank|choke|"
    r"wanna play|let'?s play|can i play|"
    r"so hard|getting hard|i'?m hard|im hard|rock hard|"
    r"turn(?:s)? me on|so horny|i'?m horny|im horny|"
    r"make me (?:cum|wet|hard)|get me off|"
    r"can i (?:touch|taste|feel|lick|kiss) (?:it|u|you|ur|your)|"
    r"wanna (?:touch|taste|feel|fuck) (?:it|u|you|ur|your)|"
    r"f+u+c+k+ (?:you|u|me)|"
    # ── Corpus-derived. He is DESCRIBING AN ACT HE WANTS. That — not arousal — is the
    # signal, and per the converting threads it is the strongest one there is: it is his
    # answer to "what would you do to me if i were there", which is the move every top
    # closer opens with. Real men who then paid $25-$45 wrote:
    #   "in doggy or missionary maybe even a blowjob"
    #   "id love to bury face and cock in that pretty pussy"
    #   "I want you gushing down my chin"
    #   "I would like to see how you touch your pussy"
    #
    # A DESIRE FRAME next to an act — not a bare anatomy word. Matching bare anatomy was
    # measured against prod and it fired on 13% of ALL inbound (vs 4% before), so recall
    # went up but the LIFT over base rate collapsed from 2.5x to 1.3x: it had widened
    # into noise. "nice tits" is arousal; "id love to bury my face in them" is intent.
    # Pricing arousal is how she reads as a bot.
    # A DESIRE FRAME near an UNAMBIGUOUS sexual token. The token list used to include
    # bare English verbs (eat / deep / touch / ride / strip / inside / ass), which made
    # ALL of these "escalation": "i need to eat dinner", "i want a deep conversation",
    # "i like riding motorcycles", "i need to touch base with my boss". With force_ask
    # on, that is a PPV for talking about dinner. Soft verbs now require a body object.
    # Subject pronoun is OPTIONAL (recall audit): fans drop the "I" constantly — "wanna
    # suck your tits", "gonna make you cum". The downstream requirement (an unambiguous
    # token, OR a soft verb + body object) is what keeps it off ordinary talk even
    # without the pronoun. A bare desire verb alone matches nothing.
    r"(?:(?:i|id|i'?d|im|i'?m|u|you)\s+)?(?:want|wanna|need|love|would love|like|"
    r"gonna|gon|wish|hope|plan|dream|dying)\b[^.!?]{0,45}?"
    r"(?:\b(?:cum|cumming|cock|dick|pussy|clit|tits?|titties|nipples|blowjob|bj|"
    r"jerk|gush|squirt|throb|deepthroat|handjob|creampie|"
    r"naked|nude|horny)\b"                      # unambiguous on their own
    r"|\b(?:suck|lick|eat|finger|stroke|touch|taste|kiss|spread|fuck|bury|ride|grind)"
    r"\s+(?:on |it |that )?(?:u|you|ur|your|me|them|those)\b)|"  # soft verb + body object
    # Pronoun + penetration/act verb DIRECTLY (no desire verb): "id bury my face in your
    # pussy", "id slide inside you". Anchored to a body part downstream so it can't fire
    # on "id touch base with my boss".
    r"(?:i|id|i'?d|im|i'?m)\s+(?:bury|shove|slide|slip|stick|ram|pound|eat|lick|suck)"
    r"\b[^.!?]{0,30}?\b(?:pussy|ass|cock|dick|clit|tits?|mouth|throat|face|hole)\b|"
    # Bare ACT NOUNS with no innocent reading. `doggy` and `69` were here and are NOT
    # innocent-free: "my doggy is so cute", "i love 69 degree weather".
    r"\b(?:blowjob|bj|doggy ?style|deepthroat|handjob|titfuck|creampie)\b|"
    # Imperatives aimed at HER body — a request, not a compliment. Added eat/suck/lick/
    # kiss and `me` to the object set: "eat me out", "ride me babe", "suck my dick".
    r"\b(?:show|spread|touch|rub|play with|finger|ride|bounce|eat|suck|lick|kiss)\s+"
    r"(?:me |it |that )?(?:ur|your|that|them|those|me)\b)",
    re.IGNORECASE)


def is_escalation(text: str | None) -> bool:
    """True when the fan's latest message is sexual/physical ESCALATION — the
    closer-only hot-moment signal ESCALATION_RE detects. Empty/None → False."""
    return bool(text) and bool(ESCALATION_RE.search(norm_text(text)))


# ── THREAD HEAT — the signal that actually predicts a sale ───────────────────────
# Measured on prod (2026-07-14), last fan line before a 1:1 chatter's PPV:
#
#   signal                                        BOUGHT   UNPAID   lift
#   last-message regex (is_escalation/ask)         10.7%     9.0%   1.19x   ← useless
#   THREAD HEAT (below)                            14.6%     0.6%  24.32x   ← the signal
#
# The engine was asking "was his LAST LINE dirty?". That question barely beats a coin
# flip, because a man types one dirty line in threads that go nowhere all day long. The
# question that predicts money is "is this a LIVE SEXUAL CONVERSATION HE IS IN?" — he
# said something sexual recently AND he is actually replying, not being talked at.
#
# It matches what the top closers do: they don't sell to a dirty sentence, they build a
# scene, make him describe what he wants, and sell him THAT. A bought PPV lands after
# ~3.6 fan messages and 0.82 sexual lines from her; an unbought one after 1.0 and 0.14.
_HEAT_WINDOW = 6          # messages, both directions — the current exchange
_HEAT_MIN_HIS_MSGS = 2    # he is IN it, not being monologued at


def thread_heat(messages: "list[tuple[str, str]]", window: int = _HEAT_WINDOW) -> bool:
    """Is this thread a live sexual conversation the fan is participating in?

    `messages` is the recent history as (direction, text), oldest→newest. Returns True on the moment worth selling into.
    """
    recent = list(messages)[-window:]
    his = [t for d, t in recent if d == "in"]
    if len(his) < _HEAT_MIN_HIS_MSGS:
        return False          # he isn't in the conversation — this is a monologue
    return any(is_escalation(t) or is_content_ask(t) for t in his)


async def content_payer_fans(account_id: str, fan_ids) -> set[int]:
    """Subset of `fan_ids` who have ever paid for CONTENT — a tip, or a PPV unlock.
    THE definition of "he is a customer", shared by welcome_chatter_for_info's hand-off and
    the assistant's evidence so the two can never disagree about who owns a fan.

    A SUBSCRIPTION IS NOT A PURCHASE, and that is the whole point of reading
    `messages` here rather than `fans.lifetime_spend_cents`. The rollup is fed by
    the transactions ledger, which counts `subscription` / `rebill` rows — so on a
    paid page the column crosses any threshold the moment a man subscribes, and
    every gate downstream mistakes a $9 subscriber for a buyer. Measured on prod
    2026-08-15: 1,766 fans (47% of everyone with spend > 0) have a non-zero
    lifetime and have never bought a thing; their average is $9.14, squarely inside
    the $3-12 sub band.

    A dollar threshold cannot separate them and must not be attempted: subs run
    $3-$180 and PPVs start at $3, so the bands overlap at both ends. A $12 floor
    was measured to still admit 314 sub-only fans (rebills stack) while rejecting
    539 real buyers. `messages` never sees a subscription at all, so the ambiguity
    simply does not arise — no threshold, no knob.

    Reads `messages` (because it LEADS the ledger by hours) — PLUS the transactions ledger,
    because `messages` alone is blind to a purchase whose message row we never
    ingested. OF's native welcome PPV is the live case: the fan unlocks it
    seconds after subscribing, before the thread is ever scraped, and OF emits
    no purchase event that would stamp `is_paid` later — so the buyer exists
    only in the ledger. Measured 2026-08-16: 822 of 2,035 ledger-known content
    buyers (40%) were invisible to the messages predicate; one paid a $20
    welcome PPV and was still `skipped_not_payer` every tick.

    Reading the ledger here does NOT repeat the `lifetime_spend_cents` mistake
    the docstring above warns about: the rollup is one untyped number, but
    ledger ROWS carry `kind` — 'ppv_message' / 'ppv_post' / 'tip' are content,
    'subscription' / 'rebill' are not, cleanly, no dollar threshold involved.
    Rows whose purchase didn't stand (chargedback / refund_pending) are out."""
    ids = [int(x) for x in fan_ids]
    if not ids:
        return set()
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id).where(
                Message.account_id == str(account_id),
                Message.fan_id.in_(ids),
                Message.is_unsent.is_(False),
                or_(
                    # A tip he sent. NO price filter, deliberately: OF puts a tip's
                    # dollars in `tipAmount`, not `price`, so every one of the 1,034
                    # tip rows on prod has price_cents = 0. Adding `price_cents > 0`
                    # here — the obvious symmetry with the unlock clause below —
                    # would silently drop all 366 fans who have only ever tipped.
                    and_(Message.is_tip.is_(True), Message.direction == "in"),
                    # A priced message of ours he unlocked. `is_paid` is the flag
                    # that means BOUGHT (247,677 priced rows on prod, 3,484 paid) —
                    # the same predicate `_paid_ppv_facts` calls "he paid". Do NOT
                    # also demand `purchased_at`: only 540 of those 3,484 rows carry
                    # one, so keying the purchase off the timestamp drops 85% of
                    # real buyers. The timestamp is for ORDERING a purchase, never
                    # for detecting one.
                    and_(Message.direction == "out", Message.is_paid.is_(True),
                         Message.price_cents > 0),
                ),
            )
        )).all()
        ledger = (await s.execute(
            select(Transaction.fan_id).where(
                Transaction.account_id == str(account_id),
                Transaction.fan_id.in_(ids),
                Transaction.kind.in_(("ppv_message", "ppv_post", "tip")),
                # 'pending' means payout not cleared, not payment not made —
                # the live welcome-PPV rows sit pending for days. Exclude only
                # the statuses where the money went back.
                Transaction.status.notin_(("chargedback", "refund_pending")),
            )
        )).all()
    return {int(r[0]) for r in rows} | {int(r[0]) for r in ledger}
