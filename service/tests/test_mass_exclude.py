#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import os  # noqa: E402
from _of_fixtures import UNLISTABLE_403, of_error  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from sqlalchemy import create_engine, select  # noqa: E402

import audiences  # noqa: E402
import automation_executor as ax  # noqa: E402
import lists  # noqa: E402
from audiences import MASSDMEXCLUDE_LIST  # noqa: E402
from automations import priority_mass  # noqa: E402
from db.engine import get_session, merge_ppv_exclude_into_dm  # noqa: E402
from db.models import Account, List, ListMember  # noqa: E402

PPV = "MASSppvEXCLUDE"

class FakeOFClient:
    _next_id = 7000

    def __init__(self) -> None:
        self.lists: dict[int, str] = {}
        self.members: dict[int, set] = {}
        self.pinned: set[int] = set()
        self.create_calls = 0

    def get_lists(self, limit: int = 100, offset: int = 0):
        items = [{"id": lid, "name": n} for lid, n in self.lists.items()]
        page = items[offset:offset + limit]
        return {"list": page, "hasMore": offset + limit < len(items)}

    def create_list(self, name: str):
        self.create_calls += 1
        FakeOFClient._next_id += 1
        lid = FakeOFClient._next_id
        self.lists[lid] = name
        self.members[lid] = set()
        return {"id": lid, "name": name}

    def set_list_pinned_to_chat(self, list_id, pinned):
        (self.pinned.add if pinned else self.pinned.discard)(int(list_id))

    def add_user_to_list(self, list_id, user_id):
        self.members.setdefault(int(list_id), set()).add(int(user_id))

    def remove_user_from_list(self, list_id, user_id):
        self.members.get(int(list_id), set()).discard(int(user_id))

    def seed_list(self, name: str) -> int:
        return int(self.create_list(name)["id"])

    def names(self) -> list[str]:
        return list(self.lists.values())

    def count_named(self, name: str) -> int:
        return sum(1 for n in self.lists.values() if n == name)


class ReadFailOFClient(FakeOFClient):
    def get_lists(self, limit: int = 100, offset: int = 0):
        raise RuntimeError("OF /lists read boom (429/proxy)")


class AddFailOFClient(FakeOFClient):
    def add_user_to_list(self, list_id, user_id):
        raise of_error(403, UNLISTABLE_403)


_fakes: dict[str, FakeOFClient] = {}
ax._make_client = lambda aid: _fakes.setdefault(aid, FakeOFClient())  # type: ignore[attr-defined]


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _row(aid: str, name: str):
    async with get_session() as s:
        return (await s.execute(select(List).where(
            List.account_id == aid, List.kind == "exclude", List.name == name,
        ))).scalar_one_or_none()


async def _seed_list(aid: str, name: str, members, of_list_id=None) -> int:
    async with get_session() as s:
        row = List(account_id=aid, name=name, kind="exclude", is_system=True,
                   of_list_id=of_list_id)
        s.add(row)
        await s.flush()
        for m in members:
            s.add(ListMember(list_id=row.id, fan_id=m))
        return int(row.id)


async def case_one_list_roundtrip():
    aid = "acc_me1"
    await _seed_account(aid)
    rd = await lists.add_do_not_mass(account_id=aid, fan_id=22, kind="dm")
    rp = await lists.add_do_not_mass(account_id=aid, fan_id=11, kind="ppv")
    assert rp["do_not_mass"] and rp["of_synced"], rp
    assert rd["do_not_mass"] and rd["of_synced"], rd
    assert rp["of_list_id"] == rd["of_list_id"], "both kinds land on the one OF list"
    assert await audiences.exclude_list_fan_ids(aid, MASSDMEXCLUDE_LIST) == {11, 22}
    for kind in ("ppv", "dm"):
        assert (await lists.get_do_not_mass(account_id=aid, fan_id=11, kind=kind))["do_not_mass"] is True
    await lists.remove_do_not_mass(account_id=aid, fan_id=11, kind="dm")
    assert await audiences.exclude_list_fan_ids(aid, MASSDMEXCLUDE_LIST) == {22}


async def case_ppv_never_recreated():
    aid = "acc_noppv"
    await _seed_account(aid)
    await lists.add_do_not_mass(account_id=aid, fan_id=5, kind="ppv")
    await lists.sync_mass_exclude(account_id=aid)
    assert await _row(aid, PPV) is None, "no local MASSppvEXCLUDE row"
    fake = _fakes[aid]
    assert fake.count_named(PPV) == 0, fake.names()
    assert fake.count_named(MASSDMEXCLUDE_LIST) == 1, fake.names()


async def case_every_send_reads_dm():
    aid = "acc_me2"
    await _seed_account(aid)
    await lists.add_do_not_mass(account_id=aid, fan_id=101, kind="dm")
    for priced in (True, False):
        out = await priority_mass.exclusions(aid, [101, 202], priced=priced, media=[])
        assert out.get(101) == "do_not_mass" and 202 not in out, (priced, out)
    r = await audiences.resolve_mass_audience(aid, included_users=[101, 202], exclude_list_name=MASSDMEXCLUDE_LIST)
    assert r["included_users"] == [202] and 101 in r["excluded_users"], r
    r3 = await audiences.resolve_mass_audience(aid, included_users=[101, 202])
    assert set(r3["included_users"]) == {101, 202}, r3


async def case_legacy_migrates_to_dm():
    aid = "acc_me4"
    await _seed_account(aid)
    await _seed_list(aid, "Do Not Mass", [999])
    assert (await lists.get_do_not_mass(account_id=aid, fan_id=999, kind="dm"))["do_not_mass"] is True
    assert await _row(aid, "Do Not Mass") is None, "legacy list renamed"
    assert await audiences.exclude_list_fan_ids(aid, MASSDMEXCLUDE_LIST) == {999}


async def case_merge_folds_ppv_into_dm():
    both, ppv_only = "acc_merge_both", "acc_merge_ppv"
    for aid in (both, ppv_only):
        await _seed_account(aid)
    fake = _fakes.setdefault(both, FakeOFClient())
    of_ppv = fake.seed_list(PPV)
    await _seed_list(both, PPV, [1, 2], of_list_id=of_ppv)
    await _seed_list(both, MASSDMEXCLUDE_LIST, [2, 3], of_list_id=fake.seed_list(MASSDMEXCLUDE_LIST))
    await _seed_list(ppv_only, PPV, [7])
    eng = create_engine(f"sqlite:///{_harness.DB_PATH}")
    try:
        got = {r["account_id"]: r for r in merge_ppv_exclude_into_dm(eng)}
        assert got[both] == {"account_id": both, "ppv_members": 2, "copied": 1}, got
        assert got[ppv_only] == {"account_id": ppv_only, "ppv_members": 1, "copied": 1}, got
        assert merge_ppv_exclude_into_dm(eng) == [], "second run is a no-op"
    finally:
        eng.dispose()
    for aid in (both, ppv_only):
        assert await _row(aid, PPV) is None, aid
    assert await audiences.exclude_list_fan_ids(both, MASSDMEXCLUDE_LIST) == {1, 2, 3}
    assert await audiences.exclude_list_fan_ids(ppv_only, MASSDMEXCLUDE_LIST) == {7}
    async with get_session() as s:
        orphans = (await s.execute(select(ListMember).where(
            ~ListMember.list_id.in_(select(List.id))))).scalars().all()
    assert orphans == [], "PPV members deleted with their list"
    assert fake.count_named(PPV) == 1, "the OnlyFans-side list is left alone"


async def case_first_add_mints_dm():
    aid = "acc_mint"
    await _seed_account(aid)
    r = await lists.add_do_not_mass(account_id=aid, fan_id=11, kind="dm")
    assert r["do_not_mass"] and r["of_synced"], r
    fake = _fakes[aid]
    assert fake.names() == [MASSDMEXCLUDE_LIST], fake.names()
    dm = await _row(aid, MASSDMEXCLUDE_LIST)
    assert dm.of_list_id and int(dm.of_list_id) in fake.pinned, (dm, fake.pinned)
    assert fake.members[int(dm.of_list_id)] == {11}


async def case_sync_heals_stranded():
    aid = "acc_stranded"
    await _seed_account(aid)
    await _seed_list(aid, MASSDMEXCLUDE_LIST, [501])
    res = await lists.sync_mass_exclude(account_id=aid)
    assert res["of_synced"], res
    fake = _fakes[aid]
    assert fake.count_named(MASSDMEXCLUDE_LIST) == 1, fake.names()
    dm = await _row(aid, MASSDMEXCLUDE_LIST)
    assert dm.of_list_id, dm
    assert fake.members[int(dm.of_list_id)] == {501}, "member backfilled onto OF"


async def case_paged_find_no_duplicate():
    aid = "acc_paged"
    await _seed_account(aid)
    fake = _fakes.setdefault(aid, FakeOFClient())
    for i in range(60):
        fake.seed_list(f"filler {i}")
    fake.seed_list(MASSDMEXCLUDE_LIST)
    r = await lists.add_do_not_mass(account_id=aid, fan_id=71, kind="dm")
    assert r["of_synced"], r
    assert fake.count_named(MASSDMEXCLUDE_LIST) == 1, f"no dup dm: {fake.count_named(MASSDMEXCLUDE_LIST)}"


async def case_get_lists_error_no_create():
    aid = "acc_readfail"
    await _seed_account(aid)
    _fakes[aid] = ReadFailOFClient()
    r = await lists.add_do_not_mass(account_id=aid, fan_id=81, kind="dm")
    assert r["do_not_mass"] is True and r["of_synced"] is False, r
    assert _fakes[aid].create_calls == 0, "must not create after a read failure"
    assert await audiences.exclude_list_fan_ids(aid, MASSDMEXCLUDE_LIST) == {81}, "local kept"


async def case_read_never_creates_of():
    aid = "acc_readonly"
    await _seed_account(aid)
    got = await lists.get_do_not_mass(account_id=aid, fan_id=1, kind="dm")
    assert got["do_not_mass"] is False, got
    assert aid not in _fakes or _fakes[aid].create_calls == 0, "read must not touch OF"


async def case_backfill_fail_reports_unsynced():
    aid = "acc_addfail"
    await _seed_account(aid)
    _fakes[aid] = AddFailOFClient()
    await _seed_list(aid, MASSDMEXCLUDE_LIST, [601])
    res = await lists.sync_mass_exclude(account_id=aid)
    assert res["of_synced"] is False, res
    assert res["lists"][MASSDMEXCLUDE_LIST]["add_failed"] == 1, res


async def case_remove_propagates():
    aid = "acc_remove"
    await _seed_account(aid)
    fake = _fakes.setdefault(aid, FakeOFClient())
    dm_of = fake.seed_list(MASSDMEXCLUDE_LIST)
    fake.add_user_to_list(dm_of, 42)
    await _seed_list(aid, MASSDMEXCLUDE_LIST, [42], of_list_id=dm_of)
    r = await lists.remove_do_not_mass(account_id=aid, fan_id=42, kind="dm")
    assert r["of_synced"], r
    assert 42 not in fake.members[dm_of], "fan removed from the OF list"
    assert await audiences.exclude_list_fan_ids(aid, MASSDMEXCLUDE_LIST) == set()


_harness.run(
    case_one_list_roundtrip,
    case_ppv_never_recreated,
    case_every_send_reads_dm,
    case_legacy_migrates_to_dm,
    case_merge_folds_ppv_into_dm,
    case_first_add_mints_dm,
    case_sync_heals_stranded,
    case_paged_find_no_duplicate,
    case_get_lists_error_no_create,
    case_read_never_creates_of,
    case_backfill_fail_reports_unsynced,
    case_remove_propagates,
)
