"""The Auto Mass one-message popup's break-it-once faults (scenarios/2026-11-08-auto-mass-one-message.py): lib/faults.py
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
AM_AUDIENCE = ("auto mass audience chips: All fans, Following and Send to online only share one row; changing All fans "
               "and Send to online only saves the matching user_lists and online_only fields; the list row reads the "
               "audience")
AM_ROUNDTRIP = ("auto mass: an unedited seeded audience rule opens More settings for its exclude list and saves the "
                "original steps_json byte-for-byte")
AM_EDIT_KEEPS = ("auto mass: a one-message rule with keys the form can't hold (excluded_users, filters) opens with the "
                 "Raw JSON notice and no message fields; Save changes untouched keeps its steps_json byte-for-byte")


def register(Fault) -> dict:
    return {
        # slop/run auto-mass-one-message --break --fault=auto-mass-online-chip-noop: Send to online only renders, but a
        # click no longer flips online_only (PremadeFields.tsx's chip handler), so the saved message keeps the default.
        "auto-mass-online-chip-noop": Fault(None, (AM_AUDIENCE,), browser=(
            (r"onlineOnly: !r\.onlineOnly", "onlineOnly: r.onlineOnly"),)),
        # slop/run auto-mass-one-message --break --fault=auto-mass-skip-chatted-off: a new rule's skip-chatted-with
        # default reverted to Off (premadeRows.ts `blankRow` excludeLastChatHours ""), so the form shows Off and the
        # saved message has no exclude_last_chat_hours. The legacy notice is untouched.
        "auto-mass-skip-chatted-off": Fault(None, (AM_FORM, AM_STORED), browser=(
            (r'excludeLastChatHours: (\\?")1(\\?")', r"excludeLastChatHours: \1\2"),)),
        # slop/run auto-mass-one-message --break (the scenario's FAULT; it guards the F1 blocker): readyMadeContent.ts
        # `formHoldReason` back to "more than one item" only (before the lossless round-trip gate), so a one-message
        # rule with excluded_users / filters opens the form and an untouched Save rebuilds it without them (the mass
        # would reach the excluded fans / every fan, not just online ones). The 2-message legacy rule (still "multi")
        # and the seeded audience rule (which the form holds) are untouched. The patch adds no quote of its own (next
        # dev's eval strings escape them): it keeps the multi line's own and returns null right after it.
        "auto-mass-form-takes-unknown-keys": Fault(None, (AM_EDIT_KEEPS,), browser=(
            (r'(if \(items\.length > 1\)(?:\s|\\n)*return (\\?")multi(\\?");)', r"\1 return null;"),)),
    }
