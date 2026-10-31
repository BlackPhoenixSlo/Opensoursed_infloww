"""The chat-list cache's break-it-once fault (app/lib/chatsCache.ts, checked in
scenarios/2026-10-24-big-model-dm-flood.py through lib/chats_cache_ts.mjs): lib/faults.py merges
`register(Fault)` into FAULTS. The check name lives here and the scenario imports it, so the
target can never name a check that does not exist.
"""
from __future__ import annotations

# The served JS files that bundle app/lib/chatsCache.ts in this scenario's tabs: the root layout and the
# Messages Pro, popout, Focus and Group page chunks (measured, run
# 20261030T184145Z-2026-10-24-big-model-dm-flood-break-0c52). In node it is the one module.
CHATS_CACHE_FILES = 5

SEND_BUMP = ("send bump: the sent fan's row heads its Creator's chats cache, fan id string or number, "
             "other Creators' caches untouched")


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-24-big-model-dm-flood --break --fault=chats-cache-fanid-mismatch [--no-ui]
        # app/lib/chatsCache.ts `fanRowMatcher`: the row match goes back to `withUser.id === fanId` (the
        # send path's pre-fix compare), so a string fan id never finds a number row (or the other way
        # round): the send leaves the row where it was. `sameUserId(...) && a === b` is that `===`. Caught
        # in node (lib/app_ts.py), also --no-ui. Only the send-bump check goes red: in the browser the live
        # handler's matches compare the relay's numbers with numbers.
        "chats-cache-fanid-mismatch": Fault(None, (SEND_BUMP,), browser=(
            (r"(sameUserId\)?)\(row\.withUser\?\.id, fanId\)", r"\1(row.withUser?.id, fanId) && row.withUser?.id === fanId"),
        ), browser_files=CHATS_CACHE_FILES, ts_files=1),
    }
