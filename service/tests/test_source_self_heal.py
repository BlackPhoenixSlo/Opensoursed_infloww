#!/usr/bin/env python3
"""Self-healing fans.source classification + muted-creator auto-restrict.

Regression for "lots of creators are not auto-restricted from automations": a
peer-creator first seen via the chat scrape (skip_users=all stripped the flags)
or a plain WS DM was stuck as source='onlyfans'/'unknown' forever, so the
muted-creator auto-skip (which keys on source=='creator_we_follow') never fired.
The fix lets any path that DOES carry OF's subscribedOn/subscribedBy repair the
row on conflict — UPGRADE-only, never downgrading a known classification.

Run:  ./venv/bin/python service/tests/test_source_self_heal.py
"""
import _harness  # MUST be first — binds the temp DB
_harness.bootstrap()

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import Account, Fan, SkipList
from automations._common import (
    classify_source, source_self_heal_set, MUTED_CREATOR_REASON,
)
import automation_executor  # noqa: E402
from automation_executor import _upsert_fan_identity

ACCT = "999000"
OWN = "999000"  # the creator's own OF id (never matched as a fan)


def case_classify_source_unit():
    assert classify_source(True, False) == "fan"
    assert classify_source(False, True) == "creator_we_follow"
    assert classify_source(True, True) == "fan", "subscribedOn wins (real fan)"
    assert classify_source(None, None) is None, "no flag → don't touch source"


def case_self_heal_set_only_when_flag_present():
    # No authoritative flag → empty fragment, so callers splat it as a no-op.
    assert source_self_heal_set(None, None) == {}
    assert source_self_heal_set(False, False) == {}
    # A flag → a SET fragment that targets the `source` column.
    frag = source_self_heal_set(False, True)
    assert "source" in frag and len(frag) == 1


async def _seed_fan(fan_id: int, source: str) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Account).values(id=ACCT)
            .on_conflict_do_nothing(index_elements=["id"]))
        await s.execute(
            sqlite_insert(Fan)
            .values(account_id=ACCT, fan_id=fan_id, source=source)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"], set_={"source": source})
        )
        await s.commit()


async def _source_of(fan_id: int) -> str | None:
    async with get_session() as s:
        return (await s.execute(
            select(Fan.source).where(
                Fan.account_id == ACCT, Fan.fan_id == fan_id))
        ).scalar_one_or_none()


async def _has_muted_skip(fan_id: int) -> bool:
    async with get_session() as s:
        return (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == ACCT, SkipList.fan_id == fan_id,
                SkipList.reason == MUTED_CREATOR_REASON))
        ).scalar_one_or_none() is not None


async def case_scrape_upgrades_weak_source_and_auto_restricts():
    """A muted chat whose withUser now carries subscribedBy: source flips
    onlyfans→creator_we_follow AND the muted_creator skip is written same-tick."""
    fid = 111
    await _seed_fan(fid, "onlyfans")
    async with get_session() as s:
        await _upsert_fan_identity(
            s, ACCT, fid, OWN,
            {"id": fid, "username": "promo_girl", "subscribedBy": True},
            [], last_in_at=datetime.utcnow(), last_out_at=None, is_muted=True,
        )
        await s.commit()
    assert await _source_of(fid) == "creator_we_follow", "source not healed"
    assert await _has_muted_skip(fid), "muted creator not auto-restricted"


async def case_never_downgrade_known_fan():
    """A real fan (source='fan') is never clobbered even if a payload carries
    subscribedBy, and an un-muted creator gets no muted skip."""
    fid = 222
    await _seed_fan(fid, "fan")
    async with get_session() as s:
        await _upsert_fan_identity(
            s, ACCT, fid, OWN, {"id": fid, "subscribedBy": True}, [],
            last_in_at=None, last_out_at=None, is_muted=False,
        )
        await s.commit()
    assert await _source_of(fid) == "fan", "downgraded a known fan"
    assert not await _has_muted_skip(fid)


async def case_subscribed_on_heals_stale_creator_label():
    """REGRESSION (2026-07-24): 'creator_we_follow' must NOT be a life sentence.
    It only records that we're subscribed to them — true of any fan a free page
    followed back — and being unable to wash it off left the promo-spam guards
    ignoring 71 real fans on a live account for five weeks. The moment OF says
    subscribedOn (he IS our fan), the label heals to 'fan'."""
    fid = 444
    await _seed_fan(fid, "creator_we_follow")
    async with get_session() as s:
        await _upsert_fan_identity(
            s, ACCT, fid, OWN, {"id": fid, "subscribedOn": True, "subscribedBy": True},
            [], last_in_at=None, last_out_at=None, is_muted=False,
        )
        await s.commit()
    assert await _source_of(fid) == "fan", "stale creator label never healed"


async def case_no_flag_leaves_source_untouched():
    """The common scrape/DM case (no flags in withUser) must not touch source."""
    fid = 333
    await _seed_fan(fid, "onlyfans")
    async with get_session() as s:
        await _upsert_fan_identity(
            s, ACCT, fid, OWN, {"id": fid, "username": "x"}, [],
            last_in_at=None, last_out_at=None, is_muted=None,
        )
        await s.commit()
    assert await _source_of(fid) == "onlyfans", "source changed with no flag"


async def _seed_muted_skip(fan_id: int) -> None:
    async with get_session() as s:
        await s.execute(
            sqlite_insert(SkipList)
            .values(account_id=ACCT, fan_id=fan_id, reason=MUTED_CREATOR_REASON,
                    added_at=datetime.utcnow())
            .on_conflict_do_nothing(index_elements=["account_id", "fan_id"]))
        await s.execute(
            Fan.__table__.update()
            .where(Fan.account_id == ACCT, Fan.fan_id == fan_id)
            .values(is_muted=True))


async def case_unmute_clears_skip_on_fast_skip_scrape():
    """REGRESSION (wave6 B1): un-muting an idle chat must free the creator even
    when the scrape finds no new messages (the fast-skip early return used to
    bypass the mute reconcile, so the skip and fans.is_muted stuck at 1)."""
    fid = 555
    await _seed_fan(fid, "creator_we_follow")
    await _seed_muted_skip(fid)
    assert await _has_muted_skip(fid)

    async def _nothing_new(*a, **kw):
        return [], False
    automation_executor._fetch_recent_end = _nothing_new
    res = await automation_executor._scrape_one_chat(
        ACCT, OWN, None, fid, {"id": fid}, page_size=10, max_pages=1,
        is_muted=False)
    assert res == (0, 0)
    assert not await _has_muted_skip(fid), "un-mute did not clear the skip"
    async with get_session() as s:
        muted = (await s.execute(select(Fan.is_muted).where(
            Fan.account_id == ACCT, Fan.fan_id == fid))).scalar_one()
    assert not muted, "fans.is_muted stayed 1"

    # An empty chat for a fan we have no row for must not mint one.
    await automation_executor._scrape_one_chat(
        ACCT, OWN, None, 556, {"id": 556}, page_size=10, max_pages=1,
        is_muted=True)
    assert await _source_of(556) is None, "fast-skip minted a fans row"


_harness.run(
    case_classify_source_unit,
    case_self_heal_set_only_when_flag_present,
    case_scrape_upgrades_weak_source_and_auto_restricts,
    case_never_downgrade_known_fan,
    case_subscribed_on_heals_stale_creator_label,
    case_no_flag_leaves_source_untouched,
    case_unmute_clears_skip_on_fast_skip_scrape,
)
