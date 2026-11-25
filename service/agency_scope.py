from __future__ import annotations

from sqlalchemy import select

from db.models import UserAccount


async def agency_account_ids(s, user_id: str) -> set[str]:
    return set((await s.execute(
        select(UserAccount.account_id).where(UserAccount.user_id == user_id)
    )).scalars().all())
