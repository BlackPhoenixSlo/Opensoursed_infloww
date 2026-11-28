import uuid
from contextlib import nullcontext
from datetime import datetime
from typing import Literal, NamedTuple

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_session
from db.models import LeakTrackerTenant, LeakWatch, LeakWatchOptOut, LeakWatchTombstone
from db.of_writer import immediate_session
from tenant_keys import NON_LLM_PROVIDERS, TRACKER_PROVIDER, get_key, set_keys


NOT_BOUND = "Connect the removal service again before deleting"


class Binding(NamedTuple):
    tenant_id: str
    via_instance: bool


async def insert_binding(s: AsyncSession, agency: str, tenant: str, via_instance: bool, at: datetime) -> None:
    await s.execute(sqlite_insert(LeakTrackerTenant).values(
        agency_user_id=agency, tenant_id=tenant, bound_at=at, via_instance=via_instance,
    ).on_conflict_do_nothing(index_elements=[LeakTrackerTenant.agency_user_id]))


async def bind_tenant(agency_user_id: str, tenant_id: str, *, via_instance: bool = False) -> Binding | None:
    async with get_session() as s:
        await insert_binding(s, agency_user_id, tenant_id, via_instance, datetime.utcnow())
        return await binding(agency_user_id, session=s)


async def bound_tenant(agency_user_id: str) -> str | None:
    return held.tenant_id if (held := await binding(agency_user_id)) else None


async def binding(agency_user_id: str, *, session: AsyncSession | None = None) -> Binding | None:
    async with (get_session() if session is None else nullcontext(session)) as s:
        row = (await s.execute(select(LeakTrackerTenant.tenant_id, LeakTrackerTenant.via_instance).where(
            LeakTrackerTenant.agency_user_id == agency_user_id))).first()
    return Binding(row.tenant_id, bool(row.via_instance)) if row else None


async def write_key(s: AsyncSession, agency: str, key: str) -> None:
    await set_keys(agency, {TRACKER_PROVIDER: key}, known=NON_LLM_PROVIDERS, session=s)


async def has_watches(s: AsyncSession, agency: str) -> bool:
    return await s.scalar(select(LeakWatch.id).where(LeakWatch.agency_user_id == agency).limit(1)) is not None


def _stones(agency: str):
    return select(LeakWatchTombstone.watch_id).where(LeakWatchTombstone.agency_user_id == agency)


async def has_stones(s: AsyncSession, agency: str, tenant: str | None = None) -> bool:
    q = _stones(agency)
    if tenant is not None:
        q = q.where(LeakWatchTombstone.tenant_id == tenant)
    return await s.scalar(q.limit(1)) is not None


class RetiredCredential(NamedTuple):
    tenant_id: str
    key: str


async def retired_credential(agency: str) -> RetiredCredential | None:
    async with get_session() as s:
        row = (await s.execute(select(LeakTrackerTenant.retired_tenant_id, LeakTrackerTenant.retired_key).where(
            LeakTrackerTenant.agency_user_id == agency))).first()
    return RetiredCredential(*row) if row and row.retired_tenant_id and row.retired_key else None


async def clear_retired_credential(s: AsyncSession, agency: str, tenant: str) -> None:
    await s.execute(update(LeakTrackerTenant).where(
        LeakTrackerTenant.agency_user_id == agency, LeakTrackerTenant.retired_tenant_id == tenant,
        ~_stones(agency).where(LeakWatchTombstone.tenant_id == tenant).exists(),
    ).values(retired_tenant_id=None, retired_key=None))


async def land_stone(agency: str, watch_id: str, tenant: str) -> None:
    async with immediate_session() as s:
        await s.execute(delete(LeakWatchTombstone).where(LeakWatchTombstone.watch_id == watch_id))
        await clear_retired_credential(s, agency, tenant)


async def drop_retired(agency: str, tenant: str) -> None:
    async with immediate_session() as s:
        await s.execute(delete(LeakWatchTombstone).where(
            LeakWatchTombstone.agency_user_id == agency, LeakWatchTombstone.tenant_id == tenant))
        await clear_retired_credential(s, agency, tenant)


async def opt_out(agency_user_id: str, account_id: str, *, session: AsyncSession | None = None) -> None:
    async with (get_session() if session is None else nullcontext(session)) as s:
        await s.execute(sqlite_insert(LeakWatchOptOut).values(
            agency_user_id=agency_user_id, account_id=account_id, created_at=datetime.utcnow(),
        ).on_conflict_do_nothing())


async def _insert_stones(s: AsyncSession, rows: list[tuple[LeakWatch, str]], at: datetime) -> None:
    await s.execute(sqlite_insert(LeakWatchTombstone).values([
        {"watch_id": w.watch_id, "agency_user_id": w.agency_user_id, "account_id": w.account_id,
         "tenant_id": tenant, "requested_at": at} for w, tenant in rows
    ]).on_conflict_do_nothing(index_elements=[LeakWatchTombstone.watch_id]))


async def bury_watches(s: AsyncSession, *, account_id: str | None, agency_user_id: str | None) -> list[LeakWatch]:
    if account_id is None and agency_user_id is None:
        raise ValueError("drop_watches needs an account or an Agency")
    q = select(LeakWatch, LeakTrackerTenant.tenant_id).outerjoin(
        LeakTrackerTenant, LeakTrackerTenant.agency_user_id == LeakWatch.agency_user_id)
    if account_id is not None:
        q = q.where(LeakWatch.account_id == account_id)
    if agency_user_id is not None:
        q = q.where(LeakWatch.agency_user_id == agency_user_id)
    hits = [(w, tenant) for w, tenant in (await s.execute(q)).all()]
    if not hits:
        return []
    if any(tenant is None for _, tenant in hits):
        raise HTTPException(status_code=409, detail=NOT_BOUND)
    await _insert_stones(s, hits, datetime.utcnow())
    await s.execute(delete(LeakWatch).where(LeakWatch.watch_id.in_([w.watch_id for w, _ in hits])))
    return [w for w, _ in hits]


async def persist_claim(agency: str, tenant_id: str, key: str, instance_key: str) -> Literal["bound", "rebound", "other_tenant"]:
    now = datetime.utcnow()
    async with immediate_session() as s:
        held = await binding(agency, session=s)
        if held is None:
            await insert_binding(s, agency, tenant_id, False, now)
        elif held.tenant_id != tenant_id:
            if not held.via_instance:
                return "other_tenant"
            rows = list((await s.scalars(select(LeakWatch).where(LeakWatch.agency_user_id == agency))).all())
            if rows:
                await _insert_stones(s, [(w, held.tenant_id) for w in rows], now)
            for w in rows:
                w.watch_id, w.synced_at, w.synced_paused, w.updated_at = str(uuid.uuid4()), None, None, now
            old_key = await get_key(agency, TRACKER_PROVIDER, session=s)
            retired = old_key if old_key and old_key != instance_key and await has_stones(s, agency, held.tenant_id) else None
            await s.execute(update(LeakTrackerTenant).where(LeakTrackerTenant.agency_user_id == agency)
                            .values(tenant_id=tenant_id, bound_at=now, via_instance=False,
                                    retired_tenant_id=held.tenant_id if retired else None, retired_key=retired))
        await write_key(s, agency, key)
    return "rebound" if held is not None and held.tenant_id != tenant_id else "bound"
