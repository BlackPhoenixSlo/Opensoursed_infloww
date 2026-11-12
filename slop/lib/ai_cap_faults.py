"""The daily AI spend limit flow's checks and break-it-once fault (scenarios/2026-11-11-ai-daily-cap.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

C_REFUSED = "before the raise, every Creator's Copilot suggest is refused 429 at the $1 cap and never reaches DeepSeek"
C_UI = ("Settings > AI keys shows the stored limit as $1.00 and today's DeepSeek spend, and each Save of a new limit "
        "reads Saved")
C_DB = "each UI save lands as cents: 5.00 -> 500 (desktop), then 7.50 -> 750 (phone), in account_ai_config"
C_ADMIT = ("after the raise to $5, the same Copilot suggest (over the old cap, under the new) is admitted: 200, "
           "3 suggestions, exactly one DeepSeek call")
C_SCOPED = "the other Creators keep their $1 cap and stay refused 429 (the save moved one Creator's limit)"
C_PHONE = "390x844: the limit card fits the screen (no sideways scroll; box and Save inside the viewport)"
C_5XX = "no 5xx from the relay in any browser session (OF reads left out)"


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-11-ai-daily-cap --break (client side): aiSpendCap.ts' dollarsToCents loses its x100, so
        # the box's dollars go on the wire as cents (5.00 -> 5). The cap row is then 5 and 8, the Copilot call
        # stays refused: C_DB and C_ADMIT alone (the card still reads Saved; the others never use the box).
        "ai-cap-ui-sends-dollars-as-cents": Fault(None, (C_DB, C_ADMIT), browser=(
            (r"Math\.round\(Number\(s\) \* 100\)", "Math.round(Number(s))"),), browser_files=1),
    }
