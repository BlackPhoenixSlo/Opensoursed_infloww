#!/usr/bin/env python3
"""
contact_guard_excludes / resolve_window_hours — the shared cross-automation
contact guard (audiences.py).

Proactive senders (send_followup, mass sends) build
their EXCLUDE set here: messages-out ∪ NudgeState.last_nudged_at ∪ messages-in
∪ extra ids. The two non-obvious contracts under test:

  case_outbound_and_nudgestate_union:
      a fan we DMed AND a fan nudged via NudgeState (no messages row — the
      nudge_online ledger) are BOTH excluded; older touches aren't.
  case_keeps_bots_and_blacklisted:
      bots/blacklisted fans STAY in the exclude set (regression: the old
      inline builders used recent_chat_fan_ids' include-side defaults, which
      dropped them — letting a broadcast re-message a blacklisted fan).
  case_inbound_and_extra_ids:
      inbound window + explicit extra_ids both land in the set.
  case_windows_off:
      None/0 windows → only the extra ids (guard off).
  case_resolve_mass_audience_sees_nudges:
      exclude_replied_hours on the mass-audience resolver now also excludes a
      fan whose only recent touch is a NudgeState stamp ("exclude I replied
      to" = ANY outbound touch, nudges included) — AND the fan is subtracted
      from the include side: OF's queue body has no per-user exclusion field
      (excludedUsers is silently dropped — verified live 2026-06-12), so an
      excluded id left inside userIds WOULD receive the blast.
  case_ensure_exclude_list_paginates:
      OF's /lists/{id}/users returns a BARE list with no hasMore — the sync
      must page it to exhaustion (short-page stop) and remove EVERY stale
      member, not just the first page, or fans linger excluded forever.
  case_resolve_window_hours:
      None → default; 0/negative → off; garbage → default.

Run: ./venv/bin/python service/tests/test_contact_guard.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from audiences import (  # noqa: E402
    contact_guard_excludes,
    ensure_exclude_list,
    resolve_mass_audience,
    resolve_window_hours,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, Blacklist, Fan, Message, NudgeState  # noqa: E402


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_msg(aid: str, fid: int, mid: int, direction: str,
                    age_hours: float) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fid, message_id=mid, direction=direction,
            body="hi", created_at=datetime.utcnow() - timedelta(hours=age_hours),
        ))


async def _seed_nudge(aid: str, fid: int, age_hours: float) -> None:
    async with get_session() as s:
        s.add(NudgeState(
            account_id=aid, fan_id=fid,
            last_nudged_at=datetime.utcnow() - timedelta(hours=age_hours),
            nudge_count=1, updated_at=datetime.utcnow(),
        ))


async def case_outbound_and_nudgestate_union():
    aid = "cg_union"
    await _seed_account(aid)
    await _seed_msg(aid, 11, 9001, "out", age_hours=2)    # DMed recently
    await _seed_nudge(aid, 12, age_hours=2)               # nudged recently (NO messages row)
    await _seed_msg(aid, 13, 9002, "out", age_hours=30)   # DMed long ago
    await _seed_nudge(aid, 14, age_hours=30)              # nudged long ago

    got = await contact_guard_excludes(aid, outbound_hours=12)
    assert got == {11, 12}, got


async def case_keeps_bots_and_blacklisted():
    aid = "cg_bots"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=21, is_bot=True))
        s.add(Blacklist(fan_id=22))
    await _seed_msg(aid, 21, 9101, "out", age_hours=1)
    await _seed_msg(aid, 22, 9102, "out", age_hours=1)

    got = await contact_guard_excludes(aid, outbound_hours=12)
    assert {21, 22} <= got, got  # both MUST stay excluded


async def case_inbound_and_extra_ids():
    aid = "cg_in"
    await _seed_account(aid)
    await _seed_msg(aid, 31, 9201, "in", age_hours=1)    # messaged us
    await _seed_msg(aid, 32, 9202, "in", age_hours=30)   # long ago

    got = await contact_guard_excludes(
        aid, inbound_hours=12, extra_ids=[99, 100])
    assert got == {31, 99, 100}, got


async def case_windows_off():
    aid = "cg_off"
    await _seed_account(aid)
    await _seed_msg(aid, 41, 9301, "out", age_hours=1)
    await _seed_msg(aid, 42, 9302, "in", age_hours=1)
    await _seed_nudge(aid, 43, age_hours=1)

    got = await contact_guard_excludes(
        aid, outbound_hours=0, inbound_hours=None, extra_ids=[7])
    assert got == {7}, got


async def case_resolve_mass_audience_sees_nudges():
    aid = "cg_resolve"
    await _seed_account(aid)
    await _seed_nudge(aid, 51, age_hours=1)  # only touch = a nudge

    out = await resolve_mass_audience(
        aid, included_users=[50, 51], exclude_replied_hours=12)
    assert 51 in out["excluded_users"], out
    # Excluded ids are SUBTRACTED from the include side — OF ignores
    # excludedUsers, so leaving 51 in userIds would send to them anyway.
    assert out["included_users"] == [50], out


class _BareListFake:
    """OF client stub whose /lists/{id}/users returns a BARE list (no hasMore
    envelope) — the real shape (verified live 2026-06-12). get_lists keeps the
    {list,hasMore} envelope (it sends format=infinite)."""

    LID = 7

    def __init__(self, existing):
        self.members = {int(x) for x in existing}
        self.added: list[int] = []
        self.removed: list[int] = []

    def get_lists(self, *, limit=20, offset=0):
        rows = [{"id": self.LID, "name": "Auto_Exclude"}]
        return {"list": rows[offset:offset + limit],
                "hasMore": offset + limit < len(rows)}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        ids = sorted(self.members)
        return [{"id": i} for i in ids[offset:offset + limit]]  # BARE list

    def create_list(self, name):
        raise AssertionError("Auto_Exclude already exists — should not create")

    def add_user_to_list(self, lid, uid):
        self.members.add(int(uid))
        self.added.append(int(uid))

    def remove_user_from_list(self, lid, uid):
        self.members.discard(int(uid))
        self.removed.append(int(uid))


async def case_ensure_exclude_list_paginates():
    # 250 stale members across 3 bare-list pages (100/100/50). Reconcile to
    # {1,2,3}: every stale id must be removed (proves we read past page 1).
    fake = _BareListFake(existing=range(1000, 1250))
    lid = await ensure_exclude_list("acc_pg", [1, 2, 3], client=fake)
    assert lid == _BareListFake.LID, lid
    assert fake.members == {1, 2, 3}, sorted(fake.members)[:6]
    assert set(fake.added) == {1, 2, 3}, fake.added
    assert len(fake.removed) == 250, len(fake.removed)


async def case_resolve_window_hours():
    assert resolve_window_hours(None, 12) == 12.0
    assert resolve_window_hours(8, 12) == 8.0
    assert resolve_window_hours(0, 12) == 0.0
    assert resolve_window_hours(-3, 12) == 0.0
    assert resolve_window_hours("garbage", 12) == 12.0


_harness.run(
    case_outbound_and_nudgestate_union,
    case_keeps_bots_and_blacklisted,
    case_inbound_and_extra_ids,
    case_windows_off,
    case_resolve_mass_audience_sees_nudges,
    case_ensure_exclude_list_paginates,
    case_resolve_window_hours,
)
