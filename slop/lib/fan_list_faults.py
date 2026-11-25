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
C_UNREAD = "Unread count == loaded chats"


def register(Fault) -> dict:
    return {
        "fan-list-owed-tier-lost": Fault(None, (FL_SORT_TIERS,), browser=(
            (r"(\bTIER\b[^{;]*\{(?:\\n|\s)*unread: 2,(?:\\n|\s)*owed:) 1\b", r"\1 0"),
        )),
        "fan-list-owe-count-from-unread": Fault(None, (FL_COUNTS, C_OWE), browser=(
            (r"(oweReplyCount: counted\.filter\(\(c\)\s*=>\s*)isOwed\(c\)", r"\1c.hasUnread"),
        )),
        "screen-reads-unreserved": Fault(None, (C_UNREAD, C_OWE), browser=(
            (r"s\.reserve \? Math\.max\(1, s\.perCreator - 1\) : s\.perCreator", "s.perCreator"),
        # next dev bundles lib/relaySchedule.ts into the layout's and the page's chunk (browser_files=2).
        ), browser_files=2, ts_files=0),
    }
