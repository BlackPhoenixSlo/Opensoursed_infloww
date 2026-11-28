from __future__ import annotations

from datetime import timedelta

from _kind_verdict_seeds import FAN, _fan, _in, _profile, _rows
from stateful_fake import _Response

KINDS = ("apply_profiles", "gen_info", "process_old_fans")

VERDICTS = {
    "fansly": {"apply_profiles": {"local": "same", "push": "same"},
               "gen_info": {"local": "same", "push": "same"},
               "process_old_fans": {"local": "same", "push": "same"}},
    "onlyfans": {"apply_profiles": {"local": "same", "push": "same"},
                 "gen_info": {"local": "same", "push": "same"},
                 "process_old_fans": {"local": "same", "push": "same"}},
}

PAYLOADS = {
    "apply_profiles": {"local": {}, "push": {"push_to_of": True}},
    "gen_info": {"local": {"force_ids": [int(FAN)]}, "push": {"force_ids": [int(FAN)]}},
    "process_old_fans": {"local": {"fan_ids": [int(FAN)], "flag_only": True},
                         "push": {"fan_ids": [int(FAN)], "push_to_of": True}},
}

SAME_EFFECTS = {
    "fansly": {
        "apply_profiles": {"local": ("table:fan_profiles", "table:fans"),
                           "push": ("POST /notes", "table:fan_profiles", "table:fans")},
        "gen_info": {"local": ("table:fan_profiles", "table:fans"),
                     "push": ("POST /notes", "table:fan_profiles", "table:fans")},
        "process_old_fans": {"local": ("table:skip_list",),
                             "push": ("POST /notes", "table:fan_profiles", "table:fans", "table:skip_list")},
    },
    "onlyfans": {
        "apply_profiles": {"local": ("table:fan_profiles", "table:fans"),
                           "push": ("set_fan_custom_name", "set_fan_note", "table:fan_profiles", "table:fans")},
        "gen_info": {"local": ("table:fan_profiles", "table:fans"),
                     "push": ("set_fan_note", "table:fan_profiles", "table:fans")},
        "process_old_fans": {"local": ("table:skip_list",),
                             "push": ("set_fan_custom_name", "set_fan_note", "table:fan_profiles", "table:fans",
                                      "table:skip_list")},
    },
}

SEEDS = {
    ("apply_profiles", "local"): _rows(_fan(hobbies="gym"), _profile),
    ("apply_profiles", "push"): _rows(_fan(hobbies="gym"), _profile),
    ("gen_info", "local"): _rows(_fan(notes="his own note"), _in(timedelta(hours=1))),
    ("gen_info", "push"): _rows(_fan(), _in(timedelta(hours=1))),
    ("process_old_fans", "local"): _rows(_fan()),
    ("process_old_fans", "push"): _rows(_fan(hobbies="gym"), _profile),
}

NOTES_ANSWER = "INVENTED: the POST /notes answer echoes the note with a minted id; RECIPES.md has no notes write"


def answers_notes(fake) -> None:
    dispatch = fake._dispatch

    def answer(method, url, path, params, query, body):
        if (method, path) == ("POST", "/notes"):
            return _Response({"success": True, "response": {"id": fake.mint(), **body}})
        return dispatch(method, url, path, params, query, body)
    fake._dispatch = answer


FAKE_STATE = {(kind, "push"): answers_notes for kind in KINDS}
