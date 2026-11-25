from __future__ import annotations

import re

from db.engine import get_session
from db.models import Message, Transaction
from sqlalchemy import and_, or_, select


# Phone keyboards emit curly/variant apostrophes; patterns spell a straight one, so unfolded text hid "can’t afford" from the broke-fan brake.
_SMART_PUNCT = str.maketrans({
    "’": "'", "‘": "'", "‛": "'", "′": "'", "`": "'",
    "ʼ": "'", "＇": "'", "՚": "'", "ꞌ": "'", "᾿": "'",
    "“": '"', "”": '"',
    "–": "-", "—": "-",
})


def norm_text(text: str | None) -> str:
    return (text or "").translate(_SMART_PUNCT)


CONTENT_ASK_RE = re.compile(
    r"(what else|what'?s next|whats next|show me|send (me |it |smth |something )"
    r"|got (any|anything)|anything (spicy|hot|else|for (me|us))|gimme|"
    r"i want (more|it|some)|more (pics|vids|photos|videos|content)|next one|"
    r"what (else )?(do|did) (u|you) (have|got|film)|unlock|spoil (u|you)|"
    r"in the mood|what (u|you) got"
    r"|can i see|lemme see|let me see|wanna see|want to see"
    r"|(would |i'?d )?(like|love) to see|dying to see|need to see|"
    r"any (pics?|vids?|videos?|photos?|nudes?|content)|"
    r"(send|show|do) (u|you) have|"
    r"(send|want|get|gimme|got any) (me |some |ur |your )?nudes?\b|"
    r"(do|d) ?(u|you|ya) (send|sell)\b|"
    r"send (me |ur |your |some )?(\w+ )?(pics?|vids?|videos?|photos?|content)\b|"
    r"i (want|need) (to see|you to)"
    # Never a bare `see (how|what|you|u)`: it matches 'see you later'.
    r"|see (some |the |ur |your |more |any )?"
    r"(content|pics?|photos?|vids?|videos?|nudes?|something))",
    re.IGNORECASE)


def is_content_ask(text: str | None) -> bool:
    return bool(text) and bool(CONTENT_ASK_RE.search(norm_text(text)))


# Desire frame or unambiguous token only: bare anatomy/soft verbs fired on 13% of inbound and on 'eat dinner'.
ESCALATION_RE = re.compile(
    r"(spank|choke|"
    r"wanna play|let'?s play|can i play|"
    r"so hard|getting hard|i'?m hard|im hard|rock hard|"
    r"turn(?:s)? me on|so horny|i'?m horny|im horny|"
    r"make me (?:cum|wet|hard)|get me off|"
    r"can i (?:touch|taste|feel|lick|kiss) (?:it|u|you|ur|your)|"
    r"wanna (?:touch|taste|feel|fuck) (?:it|u|you|ur|your)|"
    r"f+u+c+k+ (?:you|u|me)|"
    r"(?:(?:i|id|i'?d|im|i'?m|u|you)\s+)?(?:want|wanna|need|love|would love|like|"
    r"gonna|gon|wish|hope|plan|dream|dying)\b[^.!?]{0,45}?"
    r"(?:\b(?:cum|cumming|cock|dick|pussy|clit|tits?|titties|nipples|blowjob|bj|"
    r"jerk|gush|squirt|throb|deepthroat|handjob|creampie|"
    r"naked|nude|horny)\b"
    r"|\b(?:suck|lick|eat|finger|stroke|touch|taste|kiss|spread|fuck|bury|ride|grind)"
    r"\s+(?:on |it |that )?(?:u|you|ur|your|me|them|those)\b)|"
    r"(?:i|id|i'?d|im|i'?m)\s+(?:bury|shove|slide|slip|stick|ram|pound|eat|lick|suck)"
    r"\b[^.!?]{0,30}?\b(?:pussy|ass|cock|dick|clit|tits?|mouth|throat|face|hole)\b|"
    r"\b(?:blowjob|bj|doggy ?style|deepthroat|handjob|titfuck|creampie)\b|"
    r"\b(?:show|spread|touch|rub|play with|finger|ride|bounce|eat|suck|lick|kiss)\s+"
    r"(?:me |it |that )?(?:ur|your|that|them|those|me)\b)",
    re.IGNORECASE)


def is_escalation(text: str | None) -> bool:
    return bool(text) and bool(ESCALATION_RE.search(norm_text(text)))


_HEAT_WINDOW = 6
_HEAT_MIN_HIS_MSGS = 2


# Live sexual thread he replies in predicts a sale (measured ~24x lift); his last line alone does not (~1.2x).
def thread_heat(messages: "list[tuple[str, str]]", window: int = _HEAT_WINDOW) -> bool:
    recent = list(messages)[-window:]
    his = [t for d, t in recent if d == "in"]
    if len(his) < _HEAT_MIN_HIS_MSGS:
        return False
    return any(is_escalation(t) or is_content_ask(t) for t in his)


# A subscription is not a purchase: never read lifetime_spend_cents (it counts subs/rebills); messages + ledger kinds only.
async def content_payer_fans(account_id: str, fan_ids) -> set[int]:
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
                    # No price filter on tips: OF puts a tip's dollars in tipAmount, so price_cents is 0 on every tip row.
                    and_(Message.is_tip.is_(True), Message.direction == "in"),
                    # is_paid means bought; never key a purchase off purchased_at, few rows carry it.
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
                # 'pending' means payout not cleared, not unpaid: exclude only statuses where money went back.
                Transaction.status.notin_(("chargedback", "refund_pending")),
            )
        )).all()
    return {int(r[0]) for r in rows} | {int(r[0]) for r in ledger}
