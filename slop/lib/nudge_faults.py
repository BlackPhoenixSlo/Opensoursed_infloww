"""Nudge online's break-it-once faults: the pre-save hydrate (app/components/settings/nudgeOnlineReducer.ts
`preSaveConfig`, used by `hydrate`) and the kept draft (app/lib/pendingDraft.ts, wired by hooks/useNudgeConfig.ts and
NudgeOnlineTab). lib/faults.py merges `register(Fault)` into FAULTS. Client side: actors/ui.py rewrites the JS
`next dev` serves, never the repo files. The checks are scenarios/2026-10-29-state-reducers.py's (section 5, `_nudge`):
NUDGE_ABA: Save on Creator A, A -> B -> A while its PUT is held at the browser's wire, the PUT let through while A's
config refetch is held there (a slow read; bypass, declared) until "Saving…" is gone and Jitter typed if a form is
drawn, Jitter typed once the form takes it, then Save.
NUDGE_TAB_CLOSED / NUDGE_ACK_LOST: on pages of their own, a tab whose Save PUT is held at the browser's wire and aborted
there (it never reaches the relay), then closed; and one closed after its PUT reached the relay but before the answer
reached the tab; each reopened on a new page. A tab unmounted with its PUT still in flight is vitest's
(app/components/settings/NudgeOnlineTab.draft.test.tsx).
"""
from __future__ import annotations

NUDGE_ABA = ("nudge online: switching away and back mid-save never hydrates the pre-save config; the next Save keeps "
             "the first save's fields (GET /admin/nudge-config + account_ai_config row)")

NUDGE_TAB_CLOSED = ("nudge online: a tab whose Save PUT was aborted at the wire (never reached the relay), then "
                    "closed, reopens with the typed Delay and the restored note, the stored config unchanged; its Save "
                    "stores it and the kept draft is gone (GET /admin/nudge-config + account_ai_config row + "
                    "localStorage)")
NUDGE_ACK_LOST = ("nudge online: a tab closed after its Save PUT reached the relay but before the answer reached the "
                  "tab reopens on the stored config with no restored note, and the kept draft is gone (localStorage)")


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-29-state-reducers --break --fault=nudge-hydrate-stale-cache
        # `hydrate` takes any config again (the pending / fetchedAt < savedAt guard dropped, as before
        # 2026-10-30): back on A mid-save the form is seeded from A's pre-PUT cache and Save is live once the PUT
        # settles, so the Jitter typed before the refetch lands keeps Delay at its pre-PUT value and the next Save
        # writes it back over the first save. Served in the Nudge tab's chunk only: 1 file.
        "nudge-hydrate-stale-cache": Fault(None, (NUDGE_ABA,), browser=(
            (r"if \(preSaveConfig\(state, action\)\) return state;", "if (false) return state;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=nudge-draft-not-stashed
        # app/lib/pendingDraft.ts `stashDraft` writes nothing (as before W22: the draft lived in the tab only), so
        # neither the stash before the PUT nor usePendingDraft's writes land: the tab closed mid-PUT reopens on the
        # stored config. The ack-lost reopen has no draft to drop either way: only NUDGE_TAB_CLOSED goes red.
        "nudge-draft-not-stashed": Fault(None, (NUDGE_TAB_CLOSED,), browser=(
            (r"function stashDraft\(key, entry\) \{", "function stashDraft(key, entry) { return false;"),
        )),
        # slop/run 2026-10-29-state-reducers --break --fault=nudge-draft-kept-after-ack
        # app/lib/pendingDraft.ts `clearDraft` drops nothing: the ack (useSaveNudgeConfig's onSuccess) and the clean
        # form (usePendingDraft's null) leave the kept draft behind. Both checks read the key after their ack /
        # reopen, so both go red; the reopened forms still look right (the hydrate drops a draft equal to the server).
        "nudge-draft-kept-after-ack": Fault(None, (NUDGE_ACK_LOST, NUDGE_TAB_CLOSED), browser=(
            (r"function clearDraft\(key, ifEquals\) \{", "function clearDraft(key, ifEquals) { return false;"),
        )),
    }
