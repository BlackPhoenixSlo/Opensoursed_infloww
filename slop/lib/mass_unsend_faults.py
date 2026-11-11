"""The Mass messages tab's bulk unsend fault (scenarios/2026-10-29-state-reducers.py, section mass-unsend):
lib/faults.py merges `register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's served JS
(actors/ui.py). The check name lives here and the scenario imports it, so the target can never name a check
that does not exist.

  bulk-unsend-picks-unselected   slop/run 2026-10-29-state-reducers --break --fault=bulk-unsend-picks-unselected
  auto-unsend-off-stuck          slop/run 2026-10-29-state-reducers --set only=auto-unsend --break --fault=auto-unsend-off-stuck
"""
from __future__ import annotations

MASS_BULK_UNSEND = "bulk unsend on the Mass messages tab unsends exactly the selected rows, no other row flips"
AUTO_UNSEND_SAVE = ("Mass Auto Unsend Messages tab: a model's class rows show only while its switch is on; Save "
                    "writes its 'Auto-unsend mass' rule on with exactly the classes on")
AUTO_UNSEND_OFF = ("Mass Auto Unsend Messages tab: a saved rule with every class off can still be turned off "
                   "(rows hidden, Update -> is_enabled 0, saved policy kept)")
AUTO_UNSEND_TABS = ("Smart Messages: the auto-unsend card and the scheduled list are their own tabs, "
                    "neither on Mass Messages")


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
        # app/components/settings/autoUnsendForm.ts `saveBody`: a saved rule with no class on can no longer be
        # turned off (Save stays disabled with the rows hidden); only the turn-off check goes red.
        "auto-unsend-off-stuck": Fault(None, (AUTO_UNSEND_OFF,), browser=(
            (r"\bhasRule\s*&&\s*!s\.enabled\s*\?", "false ?"),
        )),
    }
