#!/usr/bin/env python3
"""
agency_scope.agency_account_ids — the tenancy set behind every 403 "not one of yours":

  case_own_ids_only:     Agency A (two Creators) gets exactly its two ids, never B's;
                         B gets only its one.
  case_none_is_empty:    a user with no `user_accounts` rows (the Master here, an
                         unknown id) → set().
  case_ids_are_str:      every id is a str, so a str path id (`IDS["creator_a"]`) is a member.

Run: ./venv/bin/python service/tests/test_agency_scope.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB)

_harness.bootstrap()

import _agency_fixtures as fx  # noqa: E402
from agency_scope import agency_account_ids  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
A2 = "1000003"  # A's second Creator


async def _ids(user_id: str) -> set[str]:
    async with get_session() as s:
        return await agency_account_ids(s, user_id)


async def _seed_second_creator() -> None:
    async with get_session() as s:
        if await s.get(Account, A2) is None:
            s.add(Account(id=A2, nickname="creator_a2", color="#aaaaaa"))
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=A2))
            await s.commit()


async def case_own_ids_only():
    await _seed_second_creator()
    assert await _ids(IDS["agency_a_owner"]) == {IDS["creator_a"], A2}
    assert await _ids(IDS["agency_b_owner"]) == {IDS["creator_b"]}


async def case_none_is_empty():
    assert await _ids(IDS["agency_master"]) == set()
    assert await _ids("no-such-user") == set()


async def case_ids_are_str():
    await _seed_second_creator()
    ids = await _ids(IDS["agency_a_owner"])
    assert isinstance(ids, set) and ids and all(type(i) is str for i in ids), ids
    assert IDS["creator_a"] in ids


_harness.run()
