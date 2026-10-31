"""The Mass messages tab's bulk unsend fault (scenarios/2026-10-29-state-reducers.py, section mass-unsend):
lib/faults.py merges `register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's served JS
(actors/ui.py). The check name lives here and the scenario imports it, so the target can never name a check
that does not exist.

  bulk-unsend-picks-unselected   slop/run 2026-10-29-state-reducers --break --fault=bulk-unsend-picks-unselected
"""
from __future__ import annotations

MASS_BULK_UNSEND = "bulk unsend on the Mass messages tab unsends exactly the selected rows, no other row flips"


def register(Fault) -> dict:
    return {
        # app/components/settings/massUnsendRules.ts `bulkTargets`: the model chips' scope is dropped, so a bulk
        # action picks its filter's rows on EVERY Creator, the unselected ones too (the list itself still shows
        # the chip's rows: `visibleMassRows` keeps its own scope). OF's mass unsend is irreversible; only the
        # bulk unsend check goes red. `inScope(r, models) && isActionable(r)` is bulkTargets' alone
        # (visibleMassRows calls inScope without the `&&`), and the module is served in one chunk (the Smart
        # Messages page's). A pattern that matches nothing is INFRA (lib/cli.py), never NOT CAUGHT.
        "bulk-unsend-picks-unselected": Fault(None, (MASS_BULK_UNSEND,), browser=(
            (r"\binScope\(r,\s*models\)\s*&&\s*isActionable\(r\)", "true && isActionable(r)"),
        )),
    }
