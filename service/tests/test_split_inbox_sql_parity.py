#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import sqlite3  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, Chat  # noqa: E402
import split_inbox  # noqa: E402

A, B, C = "acct_parity_a", "acct_parity_b", "acct_parity_c"
INT64_MAX, INT64_MIN = 2 ** 63 - 1, -(2 ** 63)
IDS = [0, 1, 2, 3, 7, 8, 501, 502, 9_007_199_254_740_993, INT64_MAX, INT64_MIN, -5, -6,
       "abc", "--1", "fan_77", "١٢٣", "12a", "", 10 ** 18 + 1]
CHATTER = "chatter_parity"

CONFIGS = [
    {"group_count": 2, "assignments": {}, "chatter_groups": {CHATTER: 1}},
    {"group_count": 3, "assignments": {"501": 3, "2": 1, "abc": 2, "--1": 2, "-5": 3, str(INT64_MAX): 1,
                                       "9007199254740993": 2, "007": 3, "١٢٣": 3},
     "chatter_groups": {CHATTER: 2}},
    {"group_count": 9, "assignments": {"8": 9, "fan_77": 4, str(INT64_MIN): 5, "": 6},
     "chatter_groups": {CHATTER: 9}},
    {"group_count": 4, "assignments": {"3": 2}, "chatter_groups": {}},
    {"group_count": 1, "assignments": {}, "chatter_groups": {CHATTER: 1}},
]


def _seed() -> None:
    async def accounts() -> None:
        async with get_session() as s:
            for aid in (A, B, C):
                s.add(Account(id=aid, nickname=aid, color="#aaaaaa"))
    asyncio.run(accounts())
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        for aid in (A, B, C):
            for i, fid in enumerate(IDS):
                con.execute("INSERT INTO chats (account_id, fan_id, unread_count, is_pinned, is_priority,"
                            " hidden_locally, list_ids, last_message_at) VALUES (?, ?, 0, 0, 0, 0, '[]', ?)",
                            (aid, fid, f"2026-01-01 00:00:{i:02d}"))
        con.commit()
        stored = {r[0] for r in con.execute("SELECT typeof(fan_id) FROM chats")}
    finally:
        con.close()
    assert stored == {"integer", "text"}, stored


_seed()


async def _groups(cfg: dict) -> list[tuple[object, int]]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Chat.fan_id, split_inbox.group_sql(Chat.fan_id, cfg)).where(Chat.account_id == A)
        )).all()
    return [(fid, g) for fid, g in rows]


async def case_new_waiter_cannot_heal_a_stale_default():
    from db.models import User, UserAccount, UserSetting

    owner = "split_parity_owner"
    old, new = '{"group_count":2}', '{"group_count":3}'
    async with get_session() as s:
        s.add(User(id=owner, username=owner, password="unused"))
    async with get_session() as s:
        s.add(UserAccount(user_id=owner, account_id=A))
        s.add(UserSetting(user_id=owner, tab=split_inbox.DEFAULT_TAB, config_json=old))
    read_old, release = asyncio.Event(), asyncio.Event()
    resolve = split_inbox.resolve

    async def paused_resolve(session, ids):
        result = await resolve(session, ids)
        if result[A][0]["group_count"] == 2:
            read_old.set()
            await release.wait()
        return result

    async def new_waiter():
        release.set()
        return await split_inbox.config(A)

    try:
        with patch.object(split_inbox, "resolve", paused_resolve):
            first = asyncio.create_task(split_inbox.config(A))
            try:
                await asyncio.wait_for(read_old.wait(), 5)
                with sqlite3.connect(_harness.DB_PATH) as con:
                    con.execute("UPDATE user_settings SET config_json=? WHERE user_id=?", (new, owner))
                await split_inbox.default_changed(owner)
                results = await asyncio.wait_for(asyncio.gather(first, new_waiter()), 5)
                assert [cfg["group_count"] for cfg in results] == [3, 3], results
            finally:
                release.set()
                await asyncio.gather(first, return_exceptions=True)
    finally:
        split_inbox._configs.pop(A, None)
        split_inbox._inherited.discard(A)


async def case_sql_group_equals_python_group_for_every_id():
    for cfg in CONFIGS:
        rows = await _groups(cfg)
        assert len(rows) == len(IDS), rows
        wrong = [(fid, g, split_inbox.group_of(fid, cfg)) for fid, g in rows if g != split_inbox.group_of(fid, cfg)]
        assert not wrong, (cfg, wrong)


async def case_moves_win_over_the_digit_rule_both_ways():
    cfg = CONFIGS[1]
    got = dict(await _groups(cfg))
    assert got[501] == 3 and 501 % 3 + 1 != 3, "moved in"
    assert got[2] == 1 and 2 % 3 + 1 != 1, "moved out"
    assert got["abc"] == 2 and got["fan_77"] == 1, "a moved non-digit id moves; others take group 1"
    assert got[-5] == 3 and got[-6] == 1, "a negative id is not digits: group 1 unless moved"
    assert got[INT64_MAX] == 1 and got[9_007_199_254_740_993] == 2


async def case_scope_keeps_exactly_what_filter_for_keeps():
    split_inbox._configs.clear()
    for aid, cfg in zip((A, B, C), (CONFIGS[1], CONFIGS[2], CONFIGS[3])):
        split_inbox.remember(aid, cfg)
    try:
        for chatter in (CHATTER, "chatter_unbound"):
            scope = split_inbox.sql_scope(chatter, [A, B, C], Chat.account_id, Chat.fan_id)
            async with get_session() as s:
                stmt = select(Chat.account_id, Chat.fan_id).where(Chat.account_id.in_([A, B, C]))
                every = (await s.execute(stmt)).all()
                kept = set((await s.execute(stmt.where(scope[0]))).all()) if scope else set(every)
            want = set()
            for aid, fid in every:
                keep = await split_inbox.filter_for(chatter, aid)
                if keep is None or keep(fid):
                    want.add((aid, fid))
            assert kept == want, (chatter, sorted(map(str, kept ^ want)))
            assert (scope is None) == (chatter == "chatter_unbound")
    finally:
        split_inbox._configs.clear()


def case_scope_signature_tells_groups_apart():
    split_inbox._configs.clear()
    split_inbox.remember(A, {"group_count": 2, "assignments": {}, "chatter_groups": {"x": 1, "y": 2, "z": 1}})
    try:
        sig = lambda c: split_inbox.sql_scope(c, [A], Chat.account_id, Chat.fan_id)[1]
        assert sig("x") == sig("z") and sig("x") != sig("y")
    finally:
        split_inbox._configs.clear()


if __name__ == "__main__":
    _harness.run()
