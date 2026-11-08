"""service/of_consent.py — a Creator's "Auto-accept OnlyFans consent" switch.

OF flags some Creators under state consent laws (`GET /users/me`: `needConsent`,
`needConsentState` NC/AL) and then answers a media send without consent
`400 {"error":{"code":0,"message":"Consent not accepted"}}`. OF's own web client asks
"Yes?" before such a send and only then adds `isConsentAccepted: true` to the body, top
level, beside `mediaFiles` (chat and mass message builder, `MakeFeedPost getDataObject`
for posts, the story bodies; build 20260517). This switch is that "Yes" given once: while
it is on, `apply` adds the same field to every media send of the account. Off (the
default, no row) never adds it; a text-only send never carries it.

The setting is `of_consent_accepts` (db.models.OfConsentAccept), append-only: the newest
row by id is the setting and every row is who changed it and when.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

log = logging.getLogger("of-relay.of_consent")

FIELD = "isConsentAccepted"


def auto_accept(account_id: Any) -> bool:
    """Whether the account's switch is on. Sync: the send path runs in a worker
    thread. No account, no row, or a failed read is off: consent is never given
    by accident."""
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


def apply(body: dict, account_id: Any) -> None:
    """Add `isConsentAccepted: true` to an OF send body that carries media
    (`mediaFiles` non-empty) when the account's switch is on."""
    if body.get("mediaFiles") and auto_accept(account_id):
        body[FIELD] = True


async def current(s: Any, account_id: str) -> Any:
    """The account's newest row (the setting and who set it), or None (off)."""
    from sqlalchemy import select

    from db.models import OfConsentAccept
    return (await s.execute(
        select(OfConsentAccept).where(OfConsentAccept.account_id == str(account_id))
        .order_by(OfConsentAccept.id.desc()).limit(1))).scalar_one_or_none()


async def record(s: Any, account_id: str, enabled: bool, *, user_id: str | None,
                 username: str | None, employee_id: int | None, at: datetime) -> Any:
    """Append one change row; answers it."""
    from db.models import OfConsentAccept
    row = OfConsentAccept(account_id=str(account_id), enabled=bool(enabled), user_id=user_id,
                          username=username, employee_id=employee_id, at=at)
    s.add(row)
    await s.flush()
    log.info("of_consent account=%s enabled=%s user=%s employee=%s", account_id, enabled,
             user_id, employee_id)
    return row
