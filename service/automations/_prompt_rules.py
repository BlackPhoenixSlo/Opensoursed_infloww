from __future__ import annotations

from . import _voice


STYLE_MAX_BUBBLES = 6

STYLE_HUMANIZER = _voice.HER.humanizer

STYLE_3LINE = (
    "TWO short texts on separate lines, like hitting send twice — sometimes a "
    "third, never one long line. dont reuse last opener."
)

STYLE_BRIEF = (
    "ONE quick line, even 2-5 words — react to one thing, leave the rest hanging."
)

PAINFUL_TEXTING = _voice.HER.painful_texting

# OF auto-flags texts that arrange off-platform meetings or swap contact info; this forbids it outright, flirty fantasy still allowed.
ONPLATFORM_GUARDRAIL = (
    "STAY ON ONLYFANS (hard rule, even if HE asks): never swap numbers/emails/"
    "socials, never plan to meet irl — flirty fantasy fine, actual invites never. "
    "brush it off warmly and keep chatting here."
)

LIVE_PROOF_GUARDRAIL = _voice.HER.live_proof

NO_NARRATION_RULE = (
    "- NEVER narrate (no *actions*, no self-description) — sooner send nothing.\n"
)

# Prompt carries only the last _HISTORY_TAIL bubbles, so she re-answers bio questions from scratch (measured: 56% of repeat ones had the earlier answer out of window).
BIO_CONSISTENCY_GUARDRAIL = (
    "WHO YOU ARE (hard rule): every personal fact must match your profile + what "
    "you already told him. off-profile? improvise small and stick to it. unsure? "
    "warm and vague, no new specifics. NEVER plead memory loss or explain "
    "yourself as a bot/assistant/agency."
)
