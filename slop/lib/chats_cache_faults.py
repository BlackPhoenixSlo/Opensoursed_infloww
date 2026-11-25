from __future__ import annotations

CHATS_CACHE_FILES = 5

SEND_BUMP = ("send bump: the sent fan's row heads its Creator's chats cache, fan id string or number, "
             "other Creators' caches untouched")


def register(Fault) -> dict:
    return {
        "chats-cache-fanid-mismatch": Fault(None, (SEND_BUMP,), browser=(
            (r"(sameUserId\)?)\(row\.withUser\?\.id, fanId\)", r"\1(row.withUser?.id, fanId) && row.withUser?.id === fanId"),
        ), browser_files=CHATS_CACHE_FILES, ts_files=1),
    }
