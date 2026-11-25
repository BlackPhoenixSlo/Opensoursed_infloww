from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models import OfConsentAccept

log = logging.getLogger("of-relay.of_consent")

# OF answers a media send without consent 400 "Consent not accepted" for some Creators; this adds the field only while the switch is on.
FIELD = "isConsentAccepted"


def auto_accept(account_id: str | None) -> bool:
    if not account_id:
        return False
    try:
        from sqlalchemy import text

        import media_cotag
        with media_cotag._sync_engine().connect() as conn:
            row = conn.execute(text(
                "SELECT enabled FROM of_consent_accepts WHERE account_id = :a "
                "ORDER BY id DESC LIMIT 1"), {"a": str(account_id)}).first()
        return bool(row and row[0])
    except Exception:
        log.exception("of_consent: read failed (account=%s): sending without consent", account_id)
        return False


def apply(body: dict, account_id: str | None) -> None:
    if body.get("mediaFiles") and auto_accept(account_id):
        body[FIELD] = True


async def current(s: AsyncSession, account_id: str) -> OfConsentAccept | None:
    from sqlalchemy import select

    from db.models import OfConsentAccept
    return (await s.execute(
        select(OfConsentAccept).where(OfConsentAccept.account_id == str(account_id))
        .order_by(OfConsentAccept.id.desc()).limit(1))).scalar_one_or_none()


async def record(s: AsyncSession, account_id: str, enabled: bool, *, user_id: str | None,
                 username: str | None, employee_id: int | None, at: datetime) -> OfConsentAccept:
    from db.models import OfConsentAccept
    row = OfConsentAccept(account_id=str(account_id), enabled=bool(enabled), user_id=user_id,
                          username=username, employee_id=employee_id, at=at)
    s.add(row)
    await s.flush()
    log.info("of_consent account=%s enabled=%s user=%s employee=%s", account_id, enabled,
             user_id, employee_id)
    return row
