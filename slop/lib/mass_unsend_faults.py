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
        "bulk-unsend-picks-unselected": Fault(None, (MASS_BULK_UNSEND,), browser=(
            # only bulkTargets has `inScope && isActionable`, and OF's mass unsend is irreversible; no match is INFRA, never NOT CAUGHT
            (r"\binScope\(r,\s*models\)\s*&&\s*isActionable\(r\)", "true && isActionable(r)"),
        )),
        "auto-unsend-off-stuck": Fault(None, (AUTO_UNSEND_OFF,), browser=(
            (r"\bhasRule\s*&&\s*!s\.enabled\s*\?", "false ?"),
        )),
    }
