"""The Auto Post one-post popup's break-it-once fault (scenarios/2026-11-09-auto-post-one-post.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

AP_FORM = ("auto post popup (390x844 phone): the post's fields inline (no Compose button, no second dialog, no Use in "
           "rule); one post, no Post 1 / Add another post / delay / repost cycle fields, "
           "no More settings (nothing rarely used is left); Caption, media pool, Price and Auto-delete after shown; the "
           "free preview pool only once the price is above 0; a $12 post with no image waits (Create off, 'A paid post "
           "needs an image…'); nothing wider than the phone")
AP_STORED = ("auto post: Create POSTs one /admin/automation-rules whose posts[] is the one item (caption, "
             "hours_to_live 6, free again after the PPV wait; no resend_* / delay_minutes key), stored as sent (GET route "
             "and the automation_rules row), and its list row reads 'Free · caption · deletes after 6h'")
AP_LEGACY = ("auto post: an older 2-post rule with a repost cycle opens with 'Older multi-post rule — edit in Raw "
             "JSON', no post fields; Raw JSON holds its payload unchanged and Cancel leaves the row as it was")


def register(Fault) -> dict:
    return {
        # slop/run auto-post-one-post --break: the legacy detection reverted (readyMadeContent.ts `formHoldReason`
        # always null), so an older multi-post / repost rule opens the one-post fields, which would drop post 2 and
        # its repost cycle. The new rule's form and payload are untouched.
        "auto-post-legacy-composer": Fault(None, (AP_LEGACY,), browser=(
            (r"function formHoldReason\(payload, kind\) \{", r"function formHoldReason(payload, kind) { return null;"),)),
    }
