"""An install from before role enforcement was on by default, for suites that seed logins and want them
holding Admin as such an install's logins do after its boot migration.

Import only after the suite has bound its temp DB (it imports service modules).
"""
import employees
import settings_api
from db.engine import get_session
from db.models import ChatterUser
from sqlalchemy import select


async def seed_pre_enforcement_install() -> int:
    """Give every seeded link the Employee row it had before this change, made with no role, then run the
    boot migration, which gives each of those logins Admin. Returns the migration's count."""
    async with get_session() as s:
        owners = set((await s.execute(select(ChatterUser.user_id))).scalars().all())

    async def _pre_deploy(*_a, **_k):
        return 0

    original, settings_api.give_role_to_unroled = settings_api.give_role_to_unroled, _pre_deploy
    try:
        for owner in sorted(owners):
            await employees._ensure_login_mirrors(owner)
    finally:
        settings_api.give_role_to_unroled = original
    return await settings_api.migrate_role_enforcement_once()
