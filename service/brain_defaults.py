from __future__ import annotations

from copy import deepcopy
from typing import Any

from automations._voice import VOICE_HER, VOICE_HIM, norm_voice

# No time_images by design: vault media ids are unique per account.
BRAIN_DEFAULTS_HER: dict[str, Any] = {
    "persona": "You are Ava, a playful 24-year-old OnlyFans creator from Austin, Texas. You love road trips, live music, cooking for friends and your rescue cat, and you keep things flirty, warm and a little teasing.",
    # No `welcome_rules`: the welcome's SHAPE is fixed in code
    # (welcome_compose._compose_system) so every account's riff matches the local
    # template. The column survives for the settings export only.
    "location": "Austin, Texas, USA",
    # Shape parity with _serialize(). Deliberately EMPTY: the canon is per-creator
    # identity, so a starter brain ships none rather than seeding every new account
    # with Ava's hometown. The 🪄 Enrich button fills it from her own persona.
    "persona_facts": {},
    "timezone": None,
    "utc_offset": -6,
    "daily_cost_cap_cents": 100,
    "model": "deepseek-v4-flash",
    "reasoning_effort": None,
    "model_by_purpose": {},
    "time_activities": {
        "morning_1": "just woke up and made myself a coffee",
        "morning_2": "out for a morning yoga session",
        "afternoon_1": "just got back from the beach",
        "afternoon_2": "chilling at home with my cat",
        "evening": "getting ready to head out",
        "night": "just got home and gonna shower"
    },
    "time_images": {}
}

BRAIN_DEFAULTS_HIM: dict[str, Any] = {
    "persona": "You are Blake, a 30-year-old OnlyFans creator from Denver, Colorado. Gym every day, weekends in the mountains, and a dry sense of humour. You are direct and confident, you pick who gets your time, and you share content that is not anywhere else.",
    "location": "Denver, Colorado, USA",
    # Empty for the same reason hers is — the canon is per-creator identity, and
    # 🪄 Enrich fills it from whatever persona the operator actually writes.
    "persona_facts": {},
    "timezone": None,
    "utc_offset": -6,
    "daily_cost_cap_cents": 100,
    "model": "deepseek-v4-flash",
    "reasoning_effort": None,
    "model_by_purpose": {},
    "time_activities": {
        "morning_1": "just woke up, coffee first",
        "morning_2": "at the gym, mid session",
        "afternoon_1": "just got back from training",
        "afternoon_2": "at home, getting some work done",
        "evening": "cleaning up, heading out later",
        "night": "just got in, about to shower"
    },
    "time_images": {}
}

BRAIN_DEFAULTS_BY_VOICE: dict[str, dict[str, Any]] = {
    VOICE_HER: BRAIN_DEFAULTS_HER,
    VOICE_HIM: BRAIN_DEFAULTS_HIM,
}

def brain_defaults(voice: object = VOICE_HER) -> dict[str, Any]:
    # Deep copy: time_activities is nested, a shallow copy would hand out the shared default by reference and one account's edit would rewrite it. Unknown voice -> female lane.
    return deepcopy(BRAIN_DEFAULTS_BY_VOICE[norm_voice(voice)])
