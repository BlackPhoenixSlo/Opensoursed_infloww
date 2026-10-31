"""Nudge online's pre-save hydrate break-it-once fault (app/components/settings/nudgeOnlineReducer.ts
`preSaveConfig`, used by `hydrate`): lib/faults.py merges `register(Fault)` into FAULTS. Client side: actors/ui.py
rewrites the JS `next dev` serves, never the repo files. The check it targets is
scenarios/2026-10-29-state-reducers.py's NUDGE_ABA (section 5, `_nudge`): Save on Creator A, A -> B -> A while its
PUT is held at the browser's wire, the PUT let through while A's config refetch is held there (a slow read; bypass,
declared) until "Saving…" is gone and Jitter typed if a form is drawn, Jitter typed once the form takes it, then Save.
"""
from __future__ import annotations

NUDGE_ABA = ("nudge online: switching away and back mid-save never hydrates the pre-save config; the next Save keeps "
             "the first save's fields (GET /admin/nudge-config + account_ai_config row)")


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
    }
