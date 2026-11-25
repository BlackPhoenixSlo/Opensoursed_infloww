from __future__ import annotations

from datetime import datetime

from db.engine import get_session
from db.models import Fan, Message, SkipList
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


MUTED_CREATOR_REASON = "muted_creator"
MANUAL_RESTRICT_REASON = "manual_restrict"
OF_RESTRICTED_REASON = "of_restricted"
# The bot no longer writes this; stays in the hard set so operator-written or legacy rows are honoured.
LADDER_STOP_REASON = "ladder_stop"
HARD_SKIP_REASONS = frozenset(
    {MUTED_CREATOR_REASON, MANUAL_RESTRICT_REASON, OF_RESTRICTED_REASON,
     LADDER_STOP_REASON}
)


_WEAK_SOURCES = ("onlyfans", "unknown", "ledger")


def classify_source(subscribed_on, subscribed_by) -> str | None:
    if subscribed_on:
        return "fan"
    if subscribed_by:
        return "creator_we_follow"
    return None


# 'fan' heals downward over creator_we_follow (subscribedOn proves he is ours); 'fan' is never downgraded.
def source_self_heal_set(subscribed_on, subscribed_by) -> dict:
    strong = classify_source(subscribed_on, subscribed_by)
    if strong is None:
        return {}
    if strong == "fan":
        return {"source": "fan"}
    from sqlalchemy import case
    return {
        "source": case(
            (Fan.source.is_(None), strong),
            (Fan.source.in_(_WEAK_SOURCES), strong),
            else_=Fan.source,
        )
    }


_PROMO_MARKERS = ("m-editor-", "onlyfans.com", "<strong>", "<em>")


# Conservative on purpose: missing a chatty creator-bot costs cents; ignoring a real fan costs the fan.
async def load_promo_spam_ids(account_id) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id)
            .where(Fan.account_id == str(account_id),
                   Fan.source == "creator_we_follow",
                   func.coalesce(Fan.lifetime_spend_cents, 0) == 0,
                   func.coalesce(Fan.turn_counter, 0) == 0,
                   select(Message.message_id).where(
                       Message.account_id == Fan.account_id,
                       Message.fan_id == Fan.fan_id,
                       Message.direction == "in",
                       or_(*[Message.body.contains(m) for m in _PROMO_MARKERS]),
                   ).exists())
        )).all()
    return {int(r[0]) for r in rows}


def should_skip_muted_creator(fan) -> bool:
    return bool(
        fan is not None
        and getattr(fan, "is_muted", False)
        and (getattr(fan, "source", "") or "") == "creator_we_follow"
    )


async def load_hard_skip_ids(account_id) -> set[int]:
    return await _load_skip_ids(account_id, HARD_SKIP_REASONS)


async def is_hard_skipped(account_id, fan_id: int) -> bool:
    from sqlalchemy import select
    async with get_session() as s:
        row = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id == int(fan_id),
                SkipList.reason.in_(tuple(HARD_SKIP_REASONS)),
            ).limit(1)
        )).first()
    return row is not None


async def _load_skip_ids(account_id, reasons: frozenset) -> set[int]:
    from sqlalchemy import select
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.reason.in_(tuple(reasons)),
            )
        )).all()
    return {int(r[0]) for r in rows}


# Beats softer reasons but never of_restricted (stronger, drives the unread exclusion).
async def mark_muted_creator_skip(account_id, fan_id, *, now=None) -> None:
    now = now or datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            sqlite_insert(SkipList)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    reason=MUTED_CREATOR_REASON, added_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"reason": MUTED_CREATOR_REASON, "added_at": now},
                where=(SkipList.reason.is_(None)
                       | (SkipList.reason != OF_RESTRICTED_REASON)),
            )
        )


async def set_of_restricted_skip(account_id, fan_id, restricted: bool, *, now=None) -> None:
    from sqlalchemy import delete as sa_delete
    now = now or datetime.utcnow()
    async with get_session() as s:
        if restricted:
            await s.execute(
                sqlite_insert(SkipList)
                .values(account_id=str(account_id), fan_id=int(fan_id),
                        reason=OF_RESTRICTED_REASON, added_at=now)
                .on_conflict_do_update(
                    index_elements=["account_id", "fan_id"],
                    set_={"reason": OF_RESTRICTED_REASON, "added_at": now},
                )
            )
        else:
            await s.execute(
                sa_delete(SkipList).where(
                    SkipList.account_id == str(account_id),
                    SkipList.fan_id == int(fan_id),
                    SkipList.reason == OF_RESTRICTED_REASON,
                )
            )


async def load_of_restricted_ids(account_id) -> set[int]:
    from sqlalchemy import select
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.reason == OF_RESTRICTED_REASON,
            )
        )).all()
    return {int(r[0]) for r in rows}


async def automation_restrict_status(account_id, fan_id) -> dict:
    from sqlalchemy import select
    async with get_session() as s:
        row = (await s.execute(
            select(SkipList.reason).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id == int(fan_id),
            )
        )).scalar_one_or_none()
    return {"restricted": row in HARD_SKIP_REASONS, "reason": row}

