from __future__ import annotations

import functools
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from db.models import (
    Account, Employee, Fan, FanProfile, Message, Transaction,
)
from auth import assert_account_owned
from geo_timezones import resolve_timezone_for_place
import relay_hooks
from of_coerce import json_list

# Gross-paid, not settled-only: OF holds new PPV pending ~7 days, so settled-only hides a fresh purchase
_NON_REVENUE_STATUSES = ("chargedback", "refunded", "failed")


async def _ensure_account_row(s: AsyncSession, account_id: str) -> None:
    stmt = (
        sqlite_insert(Account)
        .values(id=account_id, is_active_default=False)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await s.execute(stmt)

log = logging.getLogger("of-relay.fans")

router = APIRouter()


# Cached: the fans LIST serializes through _row_to_dict and a lookup scans the zone tables
_zone_for_place = functools.lru_cache(maxsize=2048)(resolve_timezone_for_place)


def _row_to_dict(f: Fan) -> dict[str, Any]:
    d = {
        "account_id": f.account_id,
        "fan_id": f.fan_id,
        "of_username": f.of_username,
        "of_display_name": f.of_display_name,
        "avatar_url": f.avatar_url,
        "custom_nickname": f.custom_nickname,
        "generated_nickname": f.generated_nickname,
        "real_name": f.real_name,
        "his_age": f.his_age,
        "birthday": f.birthday,
        "salary": f.salary,
        "salary_frequency": f.salary_frequency,
        "last_pay_date": f.last_pay_date,
        "home_country": f.home_country,
        "home_city": f.home_city,
        "local_timezone": _zone_for_place(f.home_city, f.home_country),
        "hobbies": f.hobbies,
        "fetishes": f.fetishes,
        "self_description": f.self_description,
        "description": f.description,
        "notes": f.notes,
        "applied_notes": f.applied_notes,
        "applied_notes_at": (
            f.applied_notes_at.isoformat() if f.applied_notes_at else None
        ),
        "tags": json_list(f.tags, coerce=str),
        "lifetime_spend_cents": f.lifetime_spend_cents,
        "subscription_status": f.subscription_status,
        "subscribed_at": f.subscribed_at.isoformat() if f.subscribed_at else None,
        "last_message_received_at": (
            f.last_message_received_at.isoformat() if f.last_message_received_at else None
        ),
        "source": f.source,
        "is_followed": f.is_followed,
        "language": f.language,
        "language_source": f.language_source,
        "occupation": f.occupation,
        "employer": f.employer,
        "relationship_status": f.relationship_status,
        "partner_name": f.partner_name,
        "has_kids": f.has_kids,
        "family_names": _safe_load_obj(f.family_names),
        "pets": _safe_load_array(f.pets),
        "recent_events_timeline": _safe_load_array(f.recent_events_timeline),
        "mood_at_last_message": f.mood_at_last_message,
        "sentiment_trend": f.sentiment_trend,
        "relationship_stage": f.relationship_stage,
        "communication_style": _safe_load_obj(f.communication_style),
        "automation_paused_until": (
            f.automation_paused_until.isoformat() if f.automation_paused_until else None
        ),
        "persona_age_claimed": f.persona_age_claimed,
        "persona_location_claimed": f.persona_location_claimed,
        "persona_job_claimed": f.persona_job_claimed,
        "profile_last_synced_at": (
            f.profile_last_synced_at.isoformat() if f.profile_last_synced_at else None
        ),
        "grok_facts_updated_at": (
            f.grok_facts_updated_at.isoformat() if f.grok_facts_updated_at else None
        ),
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    }
    for extra in relay_hooks.fan_row_fields:
        d.update(extra(f))
    return d


def _safe_load_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


def _with_persona_claims(row: dict[str, Any], f: Fan) -> dict[str, Any]:
    # Both halves use parse_persona_claims (clips each claim), else the drawer shows a long claim as current and struck-through
    from automations._persona import parse_persona_claims, resolved_claims
    return {
        **row,
        "persona_claims": parse_persona_claims(f.persona_claims_json),
        "persona_claims_resolved": resolved_claims(
            f.persona_claims_json,
            age_claimed=f.persona_age_claimed,
            location_claimed=f.persona_location_claimed,
            job_claimed=f.persona_job_claimed),
    }


def _safe_load_array(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


_RELATIONSHIP_STATUSES = frozenset({
    "single", "dating", "engaged", "married",
    "divorced", "widowed", "complicated", "unknown",
})


class FanUpdateBody(BaseModel):
    custom_nickname: str | None = Field(None, description="Set null to clear")
    notes: str | None = None
    tags: list[str] | None = None
    real_name: str | None = None
    home_country: str | None = None
    home_city: str | None = None
    his_age: str | None = None
    hobbies: str | None = None
    fetishes: str | None = None
    occupation: str | None = None
    employer: str | None = None
    relationship_status: str | None = None
    partner_name: str | None = None
    has_kids: bool | None = None
    family_names: dict[str, Any] | None = None
    pets: list[Any] | None = None
    mood_at_last_message: str | None = None
    sentiment_trend: str | None = None
    relationship_stage: str | None = None
    communication_style: dict[str, Any] | None = None
    automation_paused_until: datetime | None = None
    persona_age_claimed: str | None = None
    persona_location_claimed: str | None = None
    persona_job_claimed: str | None = None
    profile_last_synced_at: datetime | None = None
    grok_facts_updated_at: datetime | None = None
    language: str | None = None
    birthday: str | None = None
    salary: str | None = None
    salary_frequency: str | None = None
    last_pay_date: str | None = None

    @field_validator("salary")
    @classmethod
    def _check_salary(cls, v: str | None) -> str | None:
        return (v or "").strip()[:64] or None

    @field_validator("salary_frequency")
    @classmethod
    def _check_salary_frequency(cls, v: str | None) -> str | None:
        if not v:
            return None
        if v not in ("weekly", "biweekly", "monthly"):
            raise ValueError("salary_frequency must be weekly, biweekly or monthly")
        return v

    @field_validator("last_pay_date")
    @classmethod
    def _check_last_pay_date(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("last_pay_date must be YYYY-MM-DD")
        if len(v) != 10:
            raise ValueError("last_pay_date must be YYYY-MM-DD")
        return v

    @field_validator("birthday")
    @classmethod
    def _check_birthday(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            datetime.strptime(f"2000-{v}", "%Y-%m-%d")
        except ValueError:
            raise ValueError("birthday must be MM-DD")
        if len(v) != 5:
            raise ValueError("birthday must be MM-DD")
        return v

    @field_validator("relationship_status")
    @classmethod
    def _check_relationship_status(cls, v: str | None) -> str | None:
        if v is None or v in _RELATIONSHIP_STATUSES:
            return v
        raise ValueError(
            f"relationship_status must be one of {sorted(_RELATIONSHIP_STATUSES)}"
        )

    @field_validator("language")
    @classmethod
    def _check_language(cls, v: str | None) -> str | None:
        if not v:
            return None
        from automations._language import norm_lang
        code = norm_lang(v)
        if not code:
            raise ValueError(f"language {v!r} is not a supported ISO 639-1 code")
        return code




# Route order: literal-third-segment routes before /{fan_id}, else "by-ids" fails int parsing and returns 422
@router.get("/admin/fans/{account_id}/by-ids")
async def fans_by_ids(
    account_id: str,
    ids: str = Query("", description="Comma-separated fan ids (max 200)"),
) -> dict[str, Any]:
    """Bulk identity lookup against our LOCAL SQLite `fans` table.

    Returns `{fans: {fan_id_str: {id, name, username, avatar}}}` for every id
    we have a row for. Missing ids are omitted; the caller decides whether
    to back-fill from OF /users/list (paying the upstream cost) or accept
    the gap. Avatars come from the WS transcoder, which writes them
    whenever a message lands — covers anyone the model has talked to.

    Used by the chat-list enrichment to instantly paint names+avatars
    from local data instead of firing 8 parallel /users/list batches on
    every chats refetch. Cap at 200 ids per call to keep the IN-clause
    scan cheap on the (account_id, fan_id) composite primary key."""
    assert_account_owned(account_id)
    parsed: list[int] = []
    for chunk in ids.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed.append(int(chunk))
        except ValueError:
            continue
    if not parsed:
        return {"fans": {}}
    parsed = parsed[:200]

    out: dict[str, dict[str, Any]] = {}
    async with get_session() as s:
        rows = (await s.execute(
            select(
                Fan.fan_id, Fan.of_username, Fan.of_display_name,
                Fan.avatar_url, Fan.custom_nickname,
            )
            .where(Fan.account_id == account_id, Fan.fan_id.in_(parsed))
        )).all()
        for fid, uname, dname, avatar, nickname in rows:
            out[str(fid)] = {
                "id": int(fid),
                "name": dname,
                "username": uname,
                "avatar": avatar,
                "customNickname": nickname,
            }
    return {"fans": out}


@router.get("/admin/fans/{account_id}/spend-batch")
async def fans_spend_batch(
    account_id: str,
    ids: str = Query("", description="Comma-separated fan ids"),
) -> dict[str, Any]:
    """Bulk spend lookup for ChatList row chips.

    Returns lifetime_spend_cents + last_purchase_at per fan, keyed by
    fan_id (string). Missing fans are omitted (frontend treats absence
    as $0 / no purchase). Caps at 200 ids per call so the index scan
    on (account_id, fan_id) stays cheap."""
    assert_account_owned(account_id)
    parsed: list[int] = []
    for chunk in ids.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed.append(int(chunk))
        except ValueError:
            continue
    if not parsed:
        return {"spend": {}}
    parsed = parsed[:200]

    out: dict[str, dict[str, Any]] = {}
    async with get_session() as s:
        rows = (await s.execute(
            select(
                Fan.fan_id,
                Fan.lifetime_spend_cents,
                Fan.subscription_status,
                Fan.subscription_expires_at,
            )
            .where(Fan.account_id == account_id, Fan.fan_id.in_(parsed))
        )).all()
        for fid, cents, sub_status, sub_expires in rows:
            out[str(fid)] = {
                "spend_cents": int(cents or 0),
                "last_purchase_at": None,
                "subscription_status": sub_status,
                "expired_at": sub_expires.isoformat() if sub_expires else None,
            }

        tx_rows = (await s.execute(
            select(Transaction.fan_id, func.max(Transaction.occurred_at))
            .where(
                Transaction.account_id == account_id,
                Transaction.fan_id.in_(parsed),
                Transaction.amount_cents > 0,
            )
            .group_by(Transaction.fan_id)
        )).all()
        for fid, ts in tx_rows:
            if fid is None:
                continue
            entry = out.setdefault(str(fid), {
                "spend_cents": 0,
                "last_purchase_at": None,
                "subscription_status": None,
                "expired_at": None,
            })
            entry["last_purchase_at"] = ts.isoformat() if ts else None

    return {"spend": out}



@router.get("/admin/fans/{account_id}/{fan_id}")
async def get_fan(account_id: str, fan_id: int) -> dict[str, Any]:
    """Return the fan row. Creates an empty stub on first access so the
    drawer always has a row to edit — avoids 404-then-create dance from
    the UI."""
    assert_account_owned(account_id)
    async with get_session() as s:
        f = await s.get(Fan, (account_id, fan_id))
        if f is None:
            # Two drawer opens race: ON CONFLICT lets the loser no-op instead of a duplicate-key 500
            await _ensure_account_row(s, account_id)
            await s.execute(
                sqlite_insert(Fan)
                .values(account_id=account_id, fan_id=fan_id, source="onlyfans")
                .on_conflict_do_nothing(index_elements=["account_id", "fan_id"])
            )
            await s.commit()
            f = await s.get(Fan, (account_id, fan_id))
        row = _with_persona_claims(_row_to_dict(f), f)
        prof = await s.get(FanProfile, (account_id, fan_id))
    row["profile"] = _profile_block(prof, f.lifetime_spend_cents or 0)
    return row


def _profile_block(prof: "FanProfile | None", lifetime_spend_cents: int) -> dict[str, Any]:
    from automations._common import build_rich_note
    if prof is None:
        return {"rich_note": "", "short_bio": None, "nickname": None,
                "q": [], "tease": [], "last_generated_at": None}
    return {
        "rich_note": build_rich_note(prof.bullet_points, prof.short_bio or "", lifetime_spend_cents),
        "short_bio": prof.short_bio,
        "nickname": prof.nickname,
        "q": [x for x in (prof.q1, prof.q2, prof.q3) if x],
        "tease": [x for x in (prof.tease1, prof.tease2, prof.tease3) if x],
        "last_generated_at": prof.last_generated_at.isoformat() if prof.last_generated_at else None,
    }


@router.get("/admin/fans/{account_id}/{fan_id}/ppv-history")
async def fan_ppv_history(
    account_id: str,
    fan_id: int,
    limit: int = Query(12, ge=1, le=200),
) -> dict[str, Any]:
    """Recent PPV unlocks by this fan — powers the spend chart in the
    fan drawer (max/avg + per-purchase price points).

    Source: the `transactions` ledger (NOT the `messages` table). The
    messages table only carries rows from after we started watching the
    account; the transactions ledger is backfilled by the Phase F
    payouts ingest, so it has historical purchases too — without it,
    long-tenure fans look empty in the chart.

    Filter: `kind='ppv_message'`, `amount_cents > 0`, and status NOT IN
    the non-revenue set (chargeback/refund/failed). We show gross-paid,
    NOT settled-only: OF holds new PPV payments in a ~7-day pending payout
    window, so a `status='cleared'`-only filter would hide a just-bought
    PPV from the chart for days. Tips are kind='tip' and so are excluded
    by the filter. Ordered newest first via the (account_id, fan_id,
    occurred_at) partial index, then reversed so the response is
    chronological (oldest → newest) — the chart reads left to right."""
    assert_account_owned(account_id)
    async with get_session() as s:
        rows = (await s.execute(
            select(
                Transaction.id,
                Transaction.message_id,
                Transaction.amount_cents,
                Transaction.net_cents,
                Transaction.fee_cents,
                Transaction.vat_cents,
                Transaction.occurred_at,
                Message.created_at.label("sent_at"),
                Message.sent_by_employee_id,
                Employee.display_name.label("employee_name"),
                Employee.color.label("employee_color"),
            )
            .select_from(Transaction)
            .outerjoin(
                Message,
                (Message.account_id == Transaction.account_id)
                & (Message.fan_id == Transaction.fan_id)
                & (Message.message_id == Transaction.message_id),
            )
            .outerjoin(Employee, Employee.id == Message.sent_by_employee_id)
            .where(
                Transaction.account_id == account_id,
                Transaction.fan_id == fan_id,
                Transaction.kind == "ppv_message",
                Transaction.amount_cents > 0,
                Transaction.status.notin_(_NON_REVENUE_STATUSES),
            )
            .order_by(Transaction.occurred_at.desc())
            .limit(limit)
        )).all()

    items = [
        {
            "transaction_id": int(r.id),
            "message_id": int(r.message_id) if r.message_id is not None else None,
            "price_cents": int(r.amount_cents or 0),
            "net_cents": int(r.net_cents) if r.net_cents is not None else None,
            "fee_cents": int(r.fee_cents) if r.fee_cents is not None else None,
            "vat_cents": int(r.vat_cents) if r.vat_cents is not None else None,
            "purchased_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "sent_at": r.sent_at.isoformat() if r.sent_at else (
                r.occurred_at.isoformat() if r.occurred_at else None
            ),
            "sent_by_employee_id": (
                int(r.sent_by_employee_id) if r.sent_by_employee_id is not None else None
            ),
            "employee_name": r.employee_name,
            "employee_color": r.employee_color,
        }
        for r in reversed(rows)
    ]
    async with get_session() as s2:
        breakdown_rows = (await s2.execute(
            select(Transaction.kind, func.sum(Transaction.amount_cents))
            .where(
                Transaction.account_id == account_id,
                Transaction.fan_id == fan_id,
                Transaction.amount_cents > 0,
                Transaction.status.notin_(_NON_REVENUE_STATUSES),
            )
            .group_by(Transaction.kind)
        )).all()
    tips_cents = 0
    messages_cents = 0
    posts_cents = 0
    for kind, total in breakdown_rows:
        cents = int(total or 0)
        if kind in ("tip", "tip_post", "tip_stream"):
            tips_cents += cents
        elif kind == "ppv_message":
            messages_cents += cents
        elif kind == "ppv_post":
            posts_cents += cents

    if items:
        prices = [it["price_cents"] for it in items]
        summary = {
            "count": len(prices),
            "max_cents": max(prices),
            "avg_cents": sum(prices) // len(prices),
            "tips_cents": tips_cents,
            "messages_cents": messages_cents,
            "posts_cents": posts_cents,
        }
    else:
        summary = {
            "count": 0, "max_cents": 0, "avg_cents": 0,
            "tips_cents": tips_cents,
            "messages_cents": messages_cents,
            "posts_cents": posts_cents,
        }
    return {"items": items, "summary": summary}


@router.patch("/admin/fans/{account_id}/{fan_id}")
async def update_fan(
    account_id: str, fan_id: int, body: FanUpdateBody = Body(...),
) -> dict[str, Any]:
    """Partial update. Only fields explicitly present in the body are
    written; null is a deliberate clear, omission is "leave alone"."""
    assert_account_owned(account_id)
    payload = body.model_dump(exclude_unset=True)
    async with get_session() as s:
        f = await s.get(Fan, (account_id, fan_id))
        if f is None:
            await _ensure_account_row(s, account_id)
            f = Fan(account_id=account_id, fan_id=fan_id, source="onlyfans")
            s.add(f)
        for k, v in payload.items():
            if k == "tags":
                f.tags = json.dumps(v or [])
            elif k == "family_names":
                f.family_names = json.dumps(v or {})
            elif k == "communication_style":
                f.communication_style = json.dumps(v or {})
            elif k == "pets":
                f.pets = json.dumps(v or [])
            # Operator-set language is authoritative: mark manual so gen_info never overwrites it
            elif k == "language":
                f.language = v or None
                f.language_source = "manual" if v else None
            else:
                setattr(f, k, v)
        f.updated_at = datetime.utcnow()
        await s.commit()
        await s.refresh(f)
        return _with_persona_claims(_row_to_dict(f), f)
