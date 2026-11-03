"""The Fan List's ranking faults (scenarios/2026-10-26-fan-list-chips.py): lib/faults.py merges
`register(Fault)` into FAULTS. Both are client side: `browser=` rewrites
app/components/chat/fanListSort.ts as the browser loads it (actors/ui.py) and as node loads it
(lib/app_ts.py, `lib/fan_list_ts.mjs`), so a `--no-ui` run catches them too. The check names
live here and the scenario imports them, so a target can never name a check that does not exist.

FL_COUNTS does not claim the restricted rule: no seeder writes a restricted Fan, so the view never
holds one; fanListSort.test.ts covers it (vitest).
"""
from __future__ import annotations

FL_SORT_KEEPS_ALL = ("Fan List sort (the app's sortFanRows in node, each Creator and All Models): every mode lists "
                     "each chat of the relay's view exactly once, Newest first in the view's own order")
FL_SORT_TIERS = ("Fan List sort: Amount spent is spend desc; Spend + unread on top is unread, then read and owed, "
                 "then the rest, spend desc in each; Spend + recency puts its high-score rows first by score desc, "
                 "then the low ones unread first, spend desc in each")
FL_COUNTS = ("Fan List chip counts (the app's chipCounts in node, each Creator and All Models) equal the relay "
             "view's: Unread, Owe reply and All (unread or owed)")
# The UI check the owe-count fault also turns red (measured: the Owe reply badge is chipCounts' number).
C_OWE = "Owe reply count == owed loaded chats, in amber, shown off and on"


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-26-fan-list-chips --break --fault=fan-list-owed-tier-lost
        # fanListSort.ts `TIER`: a read chat the Fan sent last drops to the idle tier, so Spend + unread
        # on top ranks it among the chats we answered by spend. Hybrid's `HALF_LIFE` record is untouched.
        "fan-list-owed-tier-lost": Fault(None, (FL_SORT_TIERS,), browser=(
            (r"(\bTIER\b[^{;]*\{(?:\\n|\s)*unread: 2,(?:\\n|\s)*owed:) 1\b", r"\1 0"),
        )),
        # slop/run 2026-10-26-fan-list-chips --break --fault=fan-list-owe-count-from-unread
        # fanListSort.ts `chipCounts`: Owe reply counts the unread chats, so a chat read but unanswered
        # is not counted.
        "fan-list-owe-count-from-unread": Fault(None, (FL_COUNTS, C_OWE), browser=(
            (r"(oweReplyCount: counted\.filter\(\(c\)\s*=>\s*)isOwed\(c\)", r"\1c.hasUnread"),
        )),
    }
