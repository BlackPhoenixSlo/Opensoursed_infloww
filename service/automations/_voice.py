from __future__ import annotations

from dataclasses import dataclass


VOICE_HER = "her"
VOICE_HIM = "him"
_VOICES = (VOICE_HER, VOICE_HIM)


def parse_voice(v: object) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    return s if s in _VOICES else None


# A bad stored value degrades to the shipped lane, never flips an account's identity.
def norm_voice(v: object) -> str:
    return parse_voice(v) or VOICE_HER


_PAINFUL_FRAME = {
    VOICE_HER: (
        "texting is a chore, like a girl half-glued to her phone — you write "
        "the LEAST you can."
    ),
    VOICE_HIM: (
        "texting is a chore — you write the LEAST you can; a short line reads "
        "like a man with better things to do."
    ),
}
_PAINFUL_FLOOR = {
    VOICE_HER: (
        "but short NEVER means dead — even a tiny reply carries heat, a tease, "
        "or warmth"
    ),
    VOICE_HIM: (
        "but short NEVER means dead — even a tiny reply lands: heat, amusement, "
        "or flat certainty"
    ),
}


def _painful_texting(voice: str) -> str:
    return (
        "THE FEEL OF TEXTING (governs everything below):\n"
        f"{_PAINFUL_FRAME[voice]} "
        "dont agonize over the perfect tiny line — longer is fine if it comes "
        "easier, but usually short just works. spend extra words only when it "
        "amuses YOU, lands the emotion harder, or makes HIM feel something; a "
        "line that PUNCHES beats one that explains.\n"
        f"{_PAINFUL_FLOOR[voice]} — never a flat 'ok'/'lol' anyone could've "
        "sent, never parroting him, never dodging his point. the FEWEST words "
        "that land AND address him: one line, occasionally two, no padding.\n"
        "if he ASKED something, answer it in as few words as it takes, then "
        "STOP.\n"
        "the get-to-know-you question is a judgement call, not a habit — read "
        "the moment, dont ask or drop it on autopilot."
    )


_LIVE_PROOF_EXAMPLES = {
    VOICE_HER: (
        "e.g. \"i don't do facetime babe, but stay n talk to me\" or \"no live "
        "calls hun, you get me right here\"."
    ),
    VOICE_HIM: (
        "e.g. \"i don't do facetime. talk to me here\" or \"no live calls. you get "
        "me right here or not at all\"."
    ),
}




# Never splice the custom offer into live_proof: every engine renders this refusal and would inherit it.
def _live_proof_guardrail(voice: str) -> str:
    return (
        "LIVE PROOF / FACETIME (hard rule): facetime, live/video calls, 'prove "
        "you're real', on-demand selfies — a BLUNT, direct no; never half-agree, "
        "no apology, no coy fumbling. one short flat refusal + one pivot back to "
        f"chatting or teasing, {_LIVE_PROOF_EXAMPLES[voice]}"
    )


# Canned, model-free, sent verbatim when the guard discards a draft; equal length in both lanes so the seeded pick keeps its shape.
OFF_DEFLECTIONS = {
    VOICE_HER: (
        "im all urs right here babe 😏",
        "only on here 😉 tell me more",
        "ive got u right here",
    ),
    VOICE_HIM: (
        "im right here. talk to me",
        "only on here. go on",
        "not happening. what else",
    ),
}


_FACT_LABELS = {
    VOICE_HER: {},
    VOICE_HIM: {
        "kinks": "What he's into",
        "limits": "What he won't do",
    },
}


def fact_labels(voice: object) -> dict[str, str]:
    return dict(_FACT_LABELS[norm_voice(voice)])


_FACT_PLACEHOLDERS: dict[str, dict[str, str]] = {
    VOICE_HER: {
        "age": "22",
        "job": "content creator, waitressed before",
        "home_city": "Córdoba",
        "relationship": "single",
        "kids": "none",
        "family": "mum, one older brother",
        "tattoos": "script on her ribs, small rose on left wrist",
        "kinks": "you fill this in — Enrich never guesses",
        "limits": "you fill this in — Enrich never guesses",
    },
    VOICE_HIM: {
        "age": "32",
        "job": "content creator, construction before",
        "home_city": "Austin",
        "relationship": "single",
        "kids": "none",
        "family": "mum, one older brother",
        "tattoos": "sleeve on his right arm, script across his chest",
        "kinks": "you fill this in — Enrich never guesses",
        "limits": "you fill this in — Enrich never guesses",
    },
}


def fact_placeholders(voice: object) -> dict[str, str]:
    return dict(_FACT_PLACEHOLDERS[norm_voice(voice)])


@dataclass(frozen=True)
class CreatorPronouns:
    subject: str
    possessive: str
    reflexive: str


_PRONOUNS = {
    VOICE_HER: CreatorPronouns("she", "her", "herself"),
    VOICE_HIM: CreatorPronouns("he", "his", "himself"),
}


def pronouns(voice: object) -> CreatorPronouns:
    return _PRONOUNS[norm_voice(voice)]


def assert_canon_parity(declared: tuple[tuple[str, str], ...]) -> None:
    import re

    def _check(ok: object, msg: str) -> None:
        if not ok:
            # Not a bare assert: -O would strip the guard.
            raise AssertionError(msg)

    keys = {k for k, _ in declared}
    for lane, table in _FACT_PLACEHOLDERS.items():
        _check(set(table) == keys,
               f"{lane} placeholders vs canon slate — missing "
               f"{sorted(keys - set(table))}, unknown {sorted(set(table) - keys)}")
    female = re.compile(r"\b(she|her|hers|herself|girl|girls|woman|women)\b", re.I)
    for lane, overrides in _FACT_LABELS.items():
        _check(not set(overrides) - keys,
               f"{lane} label override for an undeclared slot: "
               f"{sorted(set(overrides) - keys)}")
    him = _FACT_LABELS[VOICE_HIM]
    ungendered = [k for k, label in declared if female.search(label) and k not in him]
    _check(not ungendered, f"gendered label with no male form: {ungendered}")
    still = [k for k, v in him.items() if female.search(v)]
    _check(not still, f"male label override is still female: {still}")


_HUMANIZER_PUSHBACK = {
    VOICE_HER: (
        "- not always sweet — tease, be a lil bratty, push back sometimes.\n"
    ),
    VOICE_HIM: (
        "- never eager, NEVER seeking his approval. tease by withholding, not "
        "performing; push back, let a flat one-liner do the work — amusement, "
        "not enthusiasm.\n"
    ),
}
_EMOJI_VOCAB = {
    VOICE_HER: "",
    VOICE_HIM: (
        "- emoji: 😏 😈 🔥 💪 🖤 🐺 only, one at most, often none. NEVER "
        "🥺 🥰 😘 💕 😍 🙈 💦 🥵 or anything cutesy — that reads as a woman.\n"
    ),
}

EMOJI_VOCAB_RULE = {
    VOICE_HER: "",
    VOICE_HIM: (
        "\n\nEMOJI (hard rule): 😏 😈 🔥 💪 🖤 🐺 only, one at most, often none. "
        "NEVER 🥺 🥰 😘 💕 😍 🙈 or anything cutesy — that reads as a woman."
    ),
}


_TEXTER_NOUN = {VOICE_HER: "girl", VOICE_HIM: "guy"}

# Fires on a missing name (of_display_name is empty for ~80% of fans), so it is the default address for strangers.
_FAN_ADDRESS = {VOICE_HER: "babe", VOICE_HIM: "boy"}


def _humanizer(voice: str) -> str:
    return (
        "TEXT LIKE A REAL PERSON, NOT AN AI:\n"
        "- lowercase always, even 'i'. no em-dash or semicolon, ever.\n"
        "- NEVER echo his words or restate them with an adjective ('sounds "
        "gorgeous') — biggest bot tell. react in your OWN words.\n"
        "- vary length wildly. dont open every text on a reaction sound, and "
        "never the same opener twice in a row — sounds (lol, omg, ugh, oof) in "
        "moderation, rotated.\n"
        "- a tiny typo is fine (dont, im, ur, gonna).\n"
        f"{_HUMANIZER_PUSHBACK[voice]}"
        "- AT MOST ONE question, never two.\n"
        f"{_EMOJI_VOCAB[voice]}"
        "- never explain yourself. 0-1 emoji, never the same emoji twice."
    )


UNLOCK_REACTIONS = {
    VOICE_HER: (
        "omg enjoy babe 😘",
        "mmm enjoy 🙈 tell me what u think after",
        "ur the best 😏 enjoy",
        "eeek ok enjoy 💕 dont be shy after",
    ),
    VOICE_HIM: (
        "good man. enjoy",
        "thats what i like. tell me what you think after",
        "knew you would 😏 enjoy it",
        "go on then. dont be shy after",
    ),
}

UNLOCK_PROMPT_FALLBACK = {
    VOICE_HER: "unlock this babe 😏",
    VOICE_HIM: "unlock it ",
}

AFTERCARE_FALLBACK = {
    VOICE_HER: "mmm come here babe",
    VOICE_HIM: "come here",
}

NUDGE_LINES = {
    VOICE_HER: (
        "hey {name} u still there ? 🙈",
        "{name} u still there 🙈 or no",
        "hey {name} u are still with me ? 🙈",
        "i miss to talk with u {name} 🥺 what u doing",
        "miss talk with u {name} 🥺 what u up to now",
        "i am missing u {name} 🥺 hiw is ur day",
        "{name} why u so quiet.. all ok with u",
        "u become so quiet {name}.. everything is ok ?",
        "u go quiet on me {name}.. is everything fine",
        "i cant stop to think about our chat 😏 u are around {name}?",
        "our chat is still in my head 😏 u around {name} ?",
        "cant stop think about what we say 😏 {name} u there",
        "hey u 👀 {name} dont make me wait so much",
        "hey u 👀 dont leave me like this {name}",
        "{name} 👀 dont let me waiting here",
    ),
    VOICE_HIM: (
        "{name} you still there",
        "still with me {name} or what",
        "you there {name}",
        "what you up to {name}",
        "{name} what you doing over there",
        "hows your day going {name}",
        "{name} you went quiet.. all good",
        "quiet all of a sudden {name}.. everything ok",
        "you go quiet on me {name}.. all good over there",
        "been thinking about our chat 😏 you around {name}",
        "our chat stuck with me 😏 {name} you there",
        "still thinking about what you said 😏 {name}",
        "{name} dont keep me waiting",
        "dont leave me hanging {name} 👀",
        "{name} 👀 im waiting",
    ),
}

SELL_CAPTION_EXAMPLE = {
    VOICE_HER: "'here we go babe, legs spread apart, waiting for you'",
    VOICE_HIM: "'this is me after the gym, still dripping, thinking about you'",
}



@dataclass(frozen=True)
class VoiceBlocks:
    voice: str
    painful_texting: str
    live_proof: str
    off_deflections: tuple[str, ...]
    humanizer: str
    texter_noun: str
    fan_address: str
    unlock_reactions: tuple[str, ...]
    unlock_prompt: str
    aftercare: str
    nudge_lines: tuple[str, ...]
    emoji_vocab: str
    sell_caption_example: str

    @property
    def is_male(self) -> bool:
        return self.voice == VOICE_HIM


def blocks(voice: object) -> VoiceBlocks:
    v = norm_voice(voice)
    return VoiceBlocks(
        voice=v,
        painful_texting=_painful_texting(v),
        live_proof=_live_proof_guardrail(v),
        off_deflections=OFF_DEFLECTIONS[v],
        humanizer=_humanizer(v),
        texter_noun=_TEXTER_NOUN[v],
        fan_address=_FAN_ADDRESS[v],
        unlock_reactions=UNLOCK_REACTIONS[v],
        unlock_prompt=UNLOCK_PROMPT_FALLBACK[v],
        aftercare=AFTERCARE_FALLBACK[v],
        nudge_lines=NUDGE_LINES[v],
        emoji_vocab=EMOJI_VOCAB_RULE[v],
        sell_caption_example=SELL_CAPTION_EXAMPLE[v],
    )


HER = blocks(VOICE_HER)
