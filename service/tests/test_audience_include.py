#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import os  # noqa: E402
from _of_fixtures import UNLISTABLE_403, of_error  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import audience_include  # noqa: E402
import automation_executor as ax  # noqa: E402
from audience_include import (  # noqa: E402
    AudienceHalt, _build_autofence_blocking, audience_allows_fan,
    automation_audience, check_at_fire, filter_candidates,
)
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, Fan, List as ListModel, ListMember,
)



class FakeOF:

    def __init__(self, *, lists=None, fail_add=()):
        self.lists: dict[int, set[int]] = {int(k): set(v) for k, v in (lists or {}).items()}
        self.names: dict[int, str] = {}
        self.fail_add = {int(x) for x in fail_add}
        self.sent: list[dict] = []
        self.mass_sent: list[dict] = []
        self.added: list[tuple[int, int]] = []
        self.removed: list[tuple[int, int]] = []
        self._next_list_id = 900

    def get_lists(self, *, limit=20, offset=0):
        rows = [{"id": lid, "name": self.names.get(lid, f"list{lid}")}
                for lid in sorted(self.lists)]
        return {"list": rows[offset:offset + limit],
                "hasMore": offset + limit < len(rows)}

    def create_list(self, name):
        self._next_list_id += 1
        self.lists[self._next_list_id] = set()
        self.names[self._next_list_id] = name
        return {"id": self._next_list_id}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        members = sorted(self.lists.get(int(list_id), set()))
        return [{"id": m} for m in members[offset:offset + limit]]

    def add_user_to_list(self, list_id, user_id):
        # OF 403s the odd deleted account: un-addable, skipped and counted, not a wedge.
        if int(user_id) in self.fail_add:
            raise of_error(403, UNLISTABLE_403)
        self.added.append((int(list_id), int(user_id)))
        self.lists.setdefault(int(list_id), set()).add(int(user_id))
        return {}

    def remove_user_from_list(self, list_id, user_id):
        self.removed.append((int(list_id), int(user_id)))
        self.lists.setdefault(int(list_id), set()).discard(int(user_id))
        return {}

    def send_message(self, fan_id, text, **kw):
        self.sent.append({"fan_id": int(fan_id), "text": text, **kw})
        return {"id": 77_000 + len(self.sent)}

    def send_mass_message(self, text=None, **kw):
        self.mass_sent.append({"text": text, **kw})
        return {"id": 88_000 + len(self.mass_sent)}

def _use_fake(fake) -> FakeOF:
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake



async def _seed_audience(
    aid: str, *, mode: str, members=(), of_list_id=500, synced_hours_ago=0.0,
    auto_add=False, meta=None, synced=True,
) -> int:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        row = ListModel(
            account_id=aid, of_list_id=of_list_id, name="VIP",
            kind=audience_include.AUDIENCE_INCLUDE_KIND, is_system=True,
            synced_at=(datetime.utcnow() - timedelta(hours=synced_hours_ago))
            if synced else None,
            sync_meta_json=json.dumps(meta) if meta else None,
        )
        s.add(row)
        await s.flush()
        for m in members:
            s.add(ListMember(list_id=row.id, fan_id=int(m)))
        s.add(AccountAiConfig(
            account_id=aid, audience_mode=mode, audience_list_id=row.id,
            audience_auto_add=auto_add))
        return int(row.id)


async def _mirror(aid: str, list_id: int) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(ListMember.fan_id).where(ListMember.list_id == list_id)
        )).scalars().all()
    return {int(r) for r in rows}



async def case_resolver_off_by_default():
    aid = "aud_off"
    async with get_session() as s:
        s.add(Account(id=aid))
    pol = await automation_audience(aid)
    assert pol.mode == "off" and pol.healthy, pol
    got = await filter_candidates(aid, [1, 2, 3], kind="x")
    assert got == [1, 2, 3], got
    ok, why = await audience_allows_fan(aid, 9, kind="x")
    assert ok and why is None, (ok, why)


async def case_shadow_counts_never_gates():
    aid = "aud_shadow"
    await _seed_audience(aid, mode="shadow", members=(1, 2))
    stats: dict = {}
    got = await filter_candidates(aid, [1, 2, 3, 4], kind="x", stats=stats,
                                  intent_ids=[3])
    assert got == [1, 2, 3, 4], got
    assert stats["audience_mode"] == "shadow", stats
    assert stats["audience_before"] == 4, stats
    assert stats["audience_skipped"] == 2, stats
    assert stats["audience_skipped_with_intent"] == 1, stats


async def case_enforce_intersects_and_extra_allowed():
    aid = "aud_enf"
    await _seed_audience(aid, mode="enforce", members=(1, 2))
    stats: dict = {}
    got = await filter_candidates(aid, [1, 2, 3, 4], kind="x", stats=stats,
                                  extra_allowed_ids=[4])
    assert got == [1, 2, 4], got
    assert stats["audience_skipped"] == 1, stats
    ok, why = await audience_allows_fan(aid, 3, kind="x")
    assert not ok and why == "outside_audience", (ok, why)


async def case_enforce_never_synced_sits_in_shadow():
    aid = "aud_pending"
    await _seed_audience(aid, mode="enforce", members=(1,), synced=False)
    pol = await automation_audience(aid)
    assert pol.mode == "shadow" and pol.configured_mode == "enforce", pol
    assert pol.reason == "pending_first_sync", pol
    got = await filter_candidates(aid, [1, 9], kind="x", policy=pol)
    assert got == [1, 9], got


async def case_enforce_stale_halts_loudly():
    aid = "aud_stale"
    await _seed_audience(aid, mode="enforce", members=(1,), synced_hours_ago=25)
    pol = await automation_audience(aid)
    assert not pol.healthy and pol.reason == "snapshot_stale", pol
    stats: dict = {}
    got = await filter_candidates(aid, [1, 2], kind="x", policy=pol, stats=stats)
    assert got == [], got
    assert stats["audience_halted"] == "snapshot_stale", stats


async def case_kill_switch_pauses_never_unscopes():
    aid = "aud_kill"
    await _seed_audience(aid, mode="enforce", members=(1,),
                         meta={"paused": True})
    stats: dict = {}
    got = await filter_candidates(aid, [1, 2], kind="x", stats=stats)
    assert got == [], got
    assert stats["audience_halted"] == "kill_switch", stats


async def case_at_fire_manual_stamp_bypasses():
    aid = "aud_atfire"
    await _seed_audience(aid, mode="enforce", members=(1,))
    ok, why = await check_at_fire(aid, 9, kind="scheduled_send",
                                  payload={"send_purpose": "manual"})
    assert ok and why == "manual", (ok, why)
    ok, why = await check_at_fire(aid, 9, kind="scheduled_send", payload={})
    assert not ok and why == "outside_audience", (ok, why)
    ok, _ = await check_at_fire(aid, 1, kind="scheduled_send", payload={})
    assert ok


async def case_scheduled_send_at_fire():
    from automations.scheduled_send import run as sched_run
    aid = "aud_sched"
    await _seed_audience(aid, mode="enforce", members=(1,))
    fake = _use_fake(FakeOF())
    out = await sched_run(aid, {"fan_id": 9, "text": "hey"}, run_id=1)
    assert out["status"] == "skipped" and out["reason"] == "audience:outside_audience", out
    assert fake.sent == [], fake.sent
    out = await sched_run(aid, {"fan_id": 9, "text": "hey",
                                "send_purpose": "manual"}, run_id=2)
    assert out["status"] in ("ok", "sent_no_id"), out
    assert len(fake.sent) == 1 and fake.sent[0]["fan_id"] == 9, fake.sent


def case_fence_build_verify_zero_diff():
    fake = FakeOF(lists={700: {2, 9}})
    built = _build_autofence_blocking(fake, 700, {1, 2, 3})
    assert fake.lists[700] == {1, 2, 3}, fake.lists
    assert built == {"size": 3, "unaddable": 0}, built
    add_order = [u for (l, u) in fake.added if l == 700]
    rem_order = [u for (l, u) in fake.removed if l == 700]
    assert add_order and rem_order and fake.added and fake.removed, "both legs ran"

    fake2 = FakeOF(lists={701: set()}, fail_add=(5,))
    built2 = _build_autofence_blocking(fake2, 701, {4, 5})
    assert built2 == {"size": 1, "unaddable": 1}, built2

    from curl_cffi.requests import exceptions as curl_exc

    # A transient add failure is not un-addable: that fan would sit outside the fence, so the build halts.
    class TimeoutOF(FakeOF):
        def add_user_to_list(self, list_id, user_id):
            if int(user_id) == 5:
                raise curl_exc.Timeout("curl: (28) Operation timed out")
            return super().add_user_to_list(list_id, user_id)
    try:
        _build_autofence_blocking(TimeoutOF(lists={703: set()}), 703, {4, 5})
        assert False, "a timed-out add must halt the fence build"
    except AudienceHalt as e:
        assert e.reason == "fence_add_failed", e.reason

    class StickyOF(FakeOF):
        def remove_user_from_list(self, list_id, user_id):
            return {}
    fake3 = StickyOF(lists={702: {8}})
    try:
        _build_autofence_blocking(fake3, 702, set())
        assert False, "verify must catch the sticky member"
    except AudienceHalt as e:
        assert e.reason == "fence_verify_diff", e.reason


def case_fence_lookup_incomplete_halts_never_creates():
    class RepeatListsOF(FakeOF):
        def get_lists(self, *, limit=20, offset=0):
            return super().get_lists(limit=limit, offset=0)
    fake = RepeatListsOF(lists={k: set() for k in range(1, 151)})
    try:
        audience_include._find_or_create_fence_blocking(fake)
        assert False, "an incomplete lookup must halt"
    except AudienceHalt as e:
        assert e.reason == "fence_lookup_incomplete", e.reason
    assert len(fake.lists) == 150, "no list created"
    fake.names[7] = audience_include.AUTOFENCE_LIST_NAME
    assert audience_include._find_or_create_fence_blocking(fake) == 7
    plain = FakeOF(lists={1: set()})
    made = audience_include._find_or_create_fence_blocking(plain)
    assert plain.names[made] == audience_include.AUTOFENCE_LIST_NAME, plain.names


async def case_mass_send_attaches_fence():
    from automations.send_mass_message import run as mass_run
    aid = "aud_fence_mass"
    await _seed_audience(aid, mode="enforce", members=(1, 2), of_list_id=610)
    async with get_session() as s:
        for fid in (1, 2, 3, 4):
            s.add(Fan(account_id=aid, fan_id=fid))
    fake = _use_fake(FakeOF(lists={610: {1, 2}}))
    out = await mass_run(aid, {"text": "big news", "user_lists": ["fans"]},
                         run_id=1)
    assert out.get("queue_id"), out
    assert len(fake.mass_sent) == 1, fake.mass_sent
    sent = fake.mass_sent[0]
    assert sent["user_lists"] == ["fans"], sent
    fence_ids = sent.get("excluded_user_lists") or []
    assert len(fence_ids) == 1, sent
    fence = fake.lists[int(fence_ids[0])]
    assert fence == {3, 4}, fence
    assert out.get("audience_fence_list_id") == int(fence_ids[0]), out


async def case_mass_send_halts_on_unhealthy_fence():
    from automations.send_mass_message import run as mass_run
    aid = "aud_fence_halt"
    await _seed_audience(aid, mode="enforce", members=(1,), synced_hours_ago=30)
    fake = _use_fake(FakeOF())
    out = await mass_run(aid, {"text": "big news", "user_lists": ["fans"]},
                         run_id=1)
    assert out.get("status") == "error", out
    assert str(out.get("reason", "")).startswith("audience_halt:"), out
    assert fake.mass_sent == [], "an unfenced enforce-mode blast must NEVER fire"




async def case_put_branches_and_shadow_before_enforce():
    from fastapi import HTTPException

    from account_config_api import _ConfigBody, put_account_config
    aid = "aud_put"
    async with get_session() as s:
        s.add(Account(id=aid))

    try:
        await put_account_config(_ConfigBody(account_id=aid, config={
            "audience_mode": "enforce", "audience_of_list_id": 620}))
        assert False, "direct-to-enforce must 422 without the override"
    except HTTPException as e:
        assert e.status_code == 422 and "shadow" in str(e.detail), e.detail

    out = await put_account_config(_ConfigBody(account_id=aid, config={
        "audience_mode": "shadow", "audience_of_list_id": 620,
        "audience_list_name": "VIP", "audience_auto_add": True}))
    cfg = out["config"]
    assert cfg["audience_mode"] == "shadow" and cfg["audience_auto_add"], cfg
    assert cfg["audience_of_list_id"] == 620, cfg
    async with get_session() as s:
        row = (await s.execute(select(ListModel).where(
            ListModel.account_id == aid,
            ListModel.kind == audience_include.AUDIENCE_INCLUDE_KIND))).scalars().one()
        assert int(row.of_list_id) == 620 and row.name == "VIP", (row.of_list_id, row.name)

    out = await put_account_config(_ConfigBody(account_id=aid, config={
        "persona": "hello"}))
    assert out["config"]["audience_mode"] == "shadow", out["config"]

    out = await put_account_config(_ConfigBody(account_id=aid, config={
        "audience_mode": "enforce"}))
    assert out["config"]["audience_mode"] == "enforce", out["config"]

    aid2 = "aud_put2"
    async with get_session() as s:
        s.add(Account(id=aid2))
    try:
        await put_account_config(_ConfigBody(account_id=aid2,
                                             config={"audience_mode": "shadow"}))
        assert False, "mode without a folder must 422"
    except HTTPException as e:
        assert e.status_code == 422, e.detail


_harness.run()
