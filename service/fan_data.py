from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from attribution_backfill import TRACKED_STATUSES
from automations._common import build_facts_note
from db.engine import get_session
from db.models import Fan, FanProfile, Transaction

# Each load runs on its OWN session: never share an AsyncSession across branches.
_DEFAULT_LIMIT = 5000

_HEADER = [
    "fan_name", "fan_id", "chat_id", "nickname", "short_bio", "bullet_points",
    "Q1", "Q2", "Q3", "Tease1", "Tease2", "Tease3",
    "total_spend", "message_count", "last_updated", "note_on_of",
]


@dataclass
class _Row:
    fan_id: int
    fan_name: str
    nickname: str
    short_bio: str
    bullet_points: str
    q1: str
    q2: str
    q3: str
    tease1: str
    tease2: str
    tease3: str
    total_spend_cents: int
    message_count: int
    last_updated: str
    note_on_of: str


def _s(v: object) -> str:
    return "" if v is None else str(v)


async def _load_profiles(account_id: str, limit: int) -> list[FanProfile]:
    async with get_session() as s:
        return list(
            (await s.execute(
                select(FanProfile)
                .where(FanProfile.account_id == account_id)
                .order_by(FanProfile.fan_id)
                .limit(limit)
            )).scalars().all()
        )


async def _load_fans(account_id: str, fan_ids: list[int]) -> dict[int, Fan]:
    # Chunked at 900 ids: SQLite's bind-variable cap is 999 on older builds.
    out: dict[int, Fan] = {}
    if not fan_ids:
        return out
    async with get_session() as s:
        for i in range(0, len(fan_ids), 900):
            chunk = fan_ids[i:i + 900]
            rows = (await s.execute(
                select(Fan)
                .where(Fan.account_id == account_id)
                .where(Fan.fan_id.in_(chunk))
            )).scalars().all()
            out.update({int(f.fan_id): f for f in rows})
    return out


# Cleared AND pending count (pending ~7 days, as on every earnings read); chargebacks/refunds out; fan_id NULL rows (sub rebills) dropped.
async def _load_spend(account_id: str) -> dict[int, int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(
                Transaction.fan_id,
                func.sum(Transaction.amount_cents),
            )
            .where(Transaction.account_id == account_id)
            .where(Transaction.status.in_(TRACKED_STATUSES))
            .where(Transaction.fan_id.is_not(None))
            .group_by(Transaction.fan_id)
        )).all()
    return {int(fid): int(total or 0) for fid, total in rows}


def _build_rows(
    profiles: list[FanProfile],
    fans: dict[int, Fan],
    spend: dict[int, int],
) -> list[_Row]:
    out: list[_Row] = []
    for p in profiles:
        fid = int(p.fan_id)
        fan = fans.get(fid)
        fan_name = ""
        if fan is not None:
            fan_name = _s(fan.of_display_name) or _s(fan.of_username)
        fan_name = fan_name or _s(p.original_name) or str(fid)
        nickname = _s(p.nickname)
        if not nickname and fan is not None:
            nickname = _s(fan.generated_nickname) or _s(fan.custom_nickname)
        last_updated = ""
        if p.last_generated_at is not None:
            last_updated = p.last_generated_at.isoformat()
        elif fan is not None and fan.updated_at is not None:
            last_updated = fan.updated_at.isoformat()
        facts = {} if fan is None else {
            "hobbies": _s(fan.hobbies),
            "job": _s(fan.occupation),
            "relationship": _s(fan.relationship_status),
            "fetishes": _s(fan.fetishes),
            "recent_events": _s(fan.recent_events),
        }
        bullets = build_facts_note(facts, max_len=2000, short_bio=_s(p.short_bio))
        # "added" iff the note is on OF: fans.notes is mirrored only when the notice push succeeds; non-subscribers (404) stay "not added".
        note_on_of = "added" if (fan is not None and _s(fan.notes).strip()) else "not added"
        out.append(_Row(
            fan_id=fid,
            fan_name=fan_name,
            nickname=nickname,
            short_bio=_s(p.short_bio),
            bullet_points=bullets,
            q1=_s(p.q1), q2=_s(p.q2), q3=_s(p.q3),
            tease1=_s(p.tease1), tease2=_s(p.tease2), tease3=_s(p.tease3),
            total_spend_cents=int(spend.get(fid, 0)),
            message_count=int(p.message_count_at_gen or 0),
            last_updated=last_updated,
            note_on_of=note_on_of,
        ))
    return out


async def build_fan_data(account_id: str, limit: int = _DEFAULT_LIMIT) -> list[dict]:
    profiles = await _load_profiles(account_id, limit)
    fans = await _load_fans(account_id, [int(p.fan_id) for p in profiles])
    spend = await _load_spend(account_id)
    out: list[dict] = []
    for r in _build_rows(profiles, fans, spend):
        fan = fans.get(int(r.fan_id))
        out.append({
            "account_id": account_id,
            "fan_name": r.fan_name, "fan_id": r.fan_id, "chat_id": r.fan_id,
            "nickname": r.nickname, "short_bio": r.short_bio,
            "bullet_points": r.bullet_points,
            "q1": r.q1, "q2": r.q2, "q3": r.q3,
            "tease1": r.tease1, "tease2": r.tease2, "tease3": r.tease3,
            "total_spend": round(r.total_spend_cents / 100.0, 2),
            "message_count": r.message_count,
            "last_updated": r.last_updated, "note_on_of": r.note_on_of,
            "language": (fan.language if fan is not None else None),
        })
    return out
