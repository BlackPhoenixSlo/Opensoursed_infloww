from __future__ import annotations

NUDGE_ABA = ("nudge online: switching away and back mid-save never hydrates the pre-save config; the next Save keeps "
             "the first save's fields (GET /admin/nudge-config + account_ai_config row)")

NUDGE_TAB_CLOSED = ("nudge online: a tab whose Save PUT was aborted at the wire (never reached the relay), then "
                    "closed, reopens with the typed Delay and the restored note, the stored config unchanged; its Save "
                    "stores it and the kept draft is gone (GET /admin/nudge-config + account_ai_config row + "
                    "localStorage)")
NUDGE_ACK_LOST = ("nudge online: a tab closed after its Save PUT reached the relay but before the answer reached the "
                  "tab reopens on the stored config with no restored note, and the kept draft is gone (localStorage)")
NUDGE_PRESETS_PHONE = ("nudge online, 390x844 phone: the Preview time presets row stays inside the dialog (it may "
                       "scroll sideways itself), the page has no sideways scroll, and tapping the last preset (Night) "
                       "sets Hour to 23")


def register(Fault) -> dict:
    return {
        "nudge-hydrate-stale-cache": Fault(None, (NUDGE_ABA,), browser=(
            (r"if \(preSaveConfig\(state, action\)\) return state;", "if (false) return state;"),
        )),
        "nudge-draft-not-stashed": Fault(None, (NUDGE_TAB_CLOSED,), browser=(
            (r"function stashDraft\(key, entry\) \{", "function stashDraft(key, entry) { return false;"),
        )),
        "nudge-draft-kept-after-ack": Fault(None, (NUDGE_ACK_LOST, NUDGE_TAB_CLOSED), browser=(
            (r"function clearDraft\(key, ifEquals\) \{", "function clearDraft(key, ifEquals) { return false;"),
        )),
    }
