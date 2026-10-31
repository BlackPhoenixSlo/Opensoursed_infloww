"""Shared prompt constants (human style, guardrails)."""
from __future__ import annotations

from . import _voice


# ── "Human texting style" opt-in package (per-automation checkbox) ────
# OFF by default: when a flag is absent/false the calling automation runs its
# CURRENT prompt + 2-bubble cap byte-for-byte. When ON, the automation appends
# STYLE_HUMANIZER to its system prompt, adds STYLE_3LINE to its style dice, and
# raises its bubble cap to STYLE_MAX_BUBBLES. gated wholly on style_config_json
# {"welcome_chatter_for_info":bool,"autoreply":bool}.
STYLE_MAX_BUBBLES = 6   # a real texter can fire off a burst of quick texts in a row

# The "not-AI" block — the tells that make automated chat read like a person.
# Re-exported from `_voice` (female lane), same as PAINFUL_TEXTING above. Two
# spans in this block carry a voice: the pushback ATTITUDE ("a lil bratty"
# inverts a dom) and the emoji VOCABULARY, which the shipped block never names
# — so a male account's model reaches for the female sexting set by default.
STYLE_HUMANIZER = _voice.HER.humanizer

# A 3-line micro-text style (fed into split_for_bubbles' newline path → 3 bubbles).
# Pairs with STYLE_MAX_BUBBLES=3: under a 2-cap the line-3 payload would truncate.
STYLE_3LINE = (
    "TWO short texts on separate lines, like hitting send twice — sometimes a "
    "third, never one long line. dont reuse last opener."
)

# The counterweight to STYLE_3LINE — sometimes a real texter fires back ONE short
# line and DOESN'T address everything (leaves a thread hanging). This is the "vary
# it" lever: when the model writes short, the splitter yields 1 bubble instead of a
# burst, so the bubble count varies from the SOURCE rather than from code merging.
STYLE_BRIEF = (
    "ONE quick line, even 2-5 words — react to one thing, leave the rest hanging."
)

# ── The felt cost of texting (governs everything below it) ────────────
# Re-exported from `_voice`, which owns every block whose wording depends on
# whether the creator is a woman or a man. This name is the FEMALE lane and is
# byte-identical to the text that has always shipped, so the six modules that
# import it keep working untouched. A male account does not read this constant
# — it reads `_voice.blocks(voice).painful_texting`.
PAINFUL_TEXTING = _voice.HER.painful_texting

# ── On-platform guardrail (ALWAYS ON — not gated on any opt-in) ───────
# OF auto-flags any text that arranges off-platform meetings or swaps contact
# info ("Content referring to off-platform meetings between creators and fans").
# A fan pushing for a meetup/number used to drift the model into agreeing —
# this block forbids that outright while still allowing flirty fantasy. Inject
# into every conversational system prompt (autoreply / welcome_chatter_for_info).
ONPLATFORM_GUARDRAIL = (
    "STAY ON ONLYFANS (hard rule, even if HE asks): never swap numbers/emails/"
    "socials, never plan to meet irl — flirty fantasy fine, actual invites never. "
    "brush it off warmly and keep chatting here."
)

# ── Live-proof guardrail (ALWAYS ON — not gated on any opt-in) ─────────
# Fans constantly push for FaceTime / a live call / an on-demand selfie / "prove
# you're real" / "show it now". Left unaddressed the model fumbles with weak coy
# half-deflections ("hm okay") that read badly. This block makes the reply BLUNT
# and DIRECT — a flat "I don't do that" with NO apology and NO fumbling — while
# staying flirty and redirecting back to the chat. Inject into every
# conversational system prompt alongside ONPLATFORM_GUARDRAIL.
# Re-exported from `_voice` (female lane), same as PAINFUL_TEXTING above: the
# rule is identical in both lanes, only its two worked examples carry a voice.
LIVE_PROOF_GUARDRAIL = _voice.HER.live_proof

# ── Self-consistency guardrail (ALWAYS ON — not gated on any opt-in) ──
# The creator-side twin of the fan-facts block. The prompt carries only the last
# _HISTORY_TAIL bubbles, so in a long thread everything she has ever said about
# HERSELF has scrolled out — and she re-answers "where did you grow up?" from
# scratch every time. Measured on prod: 56% of repeat biographical questions
# arrived with the earlier answer already out of the window (mean gap 127
# messages), and one fan walked a thread from "soy argentina de verdad" to
# "estoy acá en Chile" to "en córdoba" before telling her "ya no creo nada".
#
# Note what this does NOT say: it does not forbid inventing. A persona can never
# cover every question a fan asks, so improvising is allowed and expected — the
# rule is that an improvised detail becomes binding the moment it is said. That
# is what makes this compose with the claimed-facts ledger rather than fight it:
# the guardrail states the rule, the ledger supplies the remembered answers.
# The prompt half of the narration rule; `_markers.strip_narration` is the
# deterministic floor under it. ONE definition because both chat engines state it
# and a house rule the two of them word differently is a house rule in name only —
# prompts like these drift. Kept next to the other guardrails, which is where every
# engine already looks for shared prompt text.
NO_NARRATION_RULE = (
    "- NEVER narrate (no *actions*, no self-description) — sooner send nothing.\n"
)

BIO_CONSISTENCY_GUARDRAIL = (
    "WHO YOU ARE (hard rule): every personal fact must match your profile + what "
    "you already told him. off-profile? improvise small and stick to it. unsure? "
    "warm and vague, no new specifics. NEVER plead memory loss or explain "
    "yourself as a bot/assistant/agency."
)
