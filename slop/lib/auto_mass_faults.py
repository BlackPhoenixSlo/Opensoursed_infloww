"""The Auto Mass one-message popup's break-it-once fault (scenarios/2026-11-08-auto-mass-one-message.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

AM_FORM = ("auto mass popup (390x844 phone): the message's fields inline (no Compose button, no second dialog); "
           "one message, no Message 1 / Add another / resend / delay fields; 'Skip fans chatted with in last' chips "
           "Off 1h 3h 8h 24h with 1h on for a new rule; More settings closed; nothing wider than the phone")
AM_STORED = ("auto mass: Create POSTs one /admin/automation-rules with the message and chat-skip value, stored as "
             "sent (GET route and automation_rules row)")
AM_LEGACY = ("auto mass: an older 2-message rule with resends opens with 'Older multi-message rule — edit in Raw JSON', "
             "no message fields; Raw JSON holds its payload unchanged and Cancel leaves the row as it was")
AM_AUDIENCE = ("auto mass audience chips: All fans, Following and Online now share one row; changing All fans and "
               "Online now saves the matching user_lists and online_only fields")
AM_ROUNDTRIP = ("auto mass: an unedited seeded audience rule opens More settings for its exclude list and saves the "
                "original steps_json byte-for-byte")


def register(Fault) -> dict:
    return {
        # slop/run auto-mass-one-message --break: a new rule's skip-chatted-with default reverted to Off
        # (premadeRows.ts `blankRow` excludeLastChatHours ""), so the form shows Off and the saved message has no
        # exclude_last_chat_hours. The legacy notice is untouched.
        "auto-mass-skip-chatted-off": Fault(None, (AM_FORM, AM_STORED), browser=(
            (r'excludeLastChatHours: (\\?")1(\\?")', r"excludeLastChatHours: \1\2"),)),
    }
