"""service/agency_scope.py — the one "which Creators are this Agency's" query: the
account ids its `user_accounts` rows link. A 403 "not one of yours" and every
tenancy filter hang off this set, so it lives in one place."""
from __future__ import annotations

from sqlalchemy import select

from db.models import UserAccount


async def agency_account_ids(s, user_id: str) -> set[str]:
    """The account ids linked to `user_id` (an Agency owner, or a Master's own links)."""
    return set((await s.execute(
        select(UserAccount.account_id).where(UserAccount.user_id == user_id)
    )).scalars().all())
