from __future__ import annotations

AM_FORM = ("auto mass popup (390x844 phone): the message's fields inline (no Compose button, no second dialog); "
           "one message, no Message 1 / Add another / resend / delay fields; 'Skip fans chatted with in last' chips "
           "Off 1h 3h 8h 24h with 1h on for a new rule; More settings closed; nothing wider than the phone")
AM_STORED = ("auto mass: Create POSTs one /admin/automation-rules with the message and chat-skip value, stored as "
             "sent (GET route and automation_rules row)")
AM_LEGACY = ("auto mass: an older 2-message rule with resends opens with 'Older multi-message rule — edit in Raw JSON', "
             "no message fields; Raw JSON holds its payload unchanged and Cancel leaves the row as it was")
AM_AUDIENCE = ("auto mass audience chips: All fans, Following and Send to online only share one row; changing All fans "
               "and Send to online only saves the matching user_lists and online_only fields; the list row reads the "
               "audience")
AM_ROUNDTRIP = ("auto mass: an unedited seeded audience rule opens More settings for its exclude list and saves the "
                "original steps_json byte-for-byte")
AM_EDIT_KEEPS = ("auto mass: a one-message rule with keys the form can't hold (excluded_users, filters) opens with the "
                 "Raw JSON notice and no message fields; Save changes untouched keeps its steps_json byte-for-byte")


def register(Fault) -> dict:
    return {
        "auto-mass-online-chip-noop": Fault(None, (AM_AUDIENCE,), browser=(
            (r"onlineOnly: !r\.onlineOnly", "onlineOnly: r.onlineOnly"),)),
        "auto-mass-skip-chatted-off": Fault(None, (AM_FORM, AM_STORED), browser=(
            (r'excludeLastChatHours: (\\?")1(\\?")', r"excludeLastChatHours: \1\2"),)),
        "auto-mass-form-takes-unknown-keys": Fault(None, (AM_EDIT_KEEPS,), browser=(
            (r'(if \(items\.length > 1\)(?:\s|\\n)*return (\\?")multi(\\?");)', r"\1 return null;"),)),
    }
