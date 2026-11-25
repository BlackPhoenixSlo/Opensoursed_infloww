from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from pydantic import BaseModel

import proxies as proxy_registry
import relay_host

log = logging.getLogger("of-relay.diag_api")

router = APIRouter()



_APP_ERROR_CONTEXT_MAX = 16384


# A raw slice of the JSON text would not parse and GET /admin/errors would 500 on it.
def _app_error_context_json(text: str) -> str:
    if len(text) <= _APP_ERROR_CONTEXT_MAX:
        return text
    return json.dumps({"truncated": text[:_APP_ERROR_CONTEXT_MAX - 64]})


def _app_error_context(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"unparsed": raw}


class _AppErrorBody(BaseModel):
    source: str = "browser"
    kind: str = "error"
    message: str
    stack: str | None = None
    url: str | None = None
    account_id: str | None = None
    employee_id: int | None = None
    user_agent: str | None = None
    context: dict[str, Any] | None = None


def _employee_ids_of(actor):
    from sqlalchemy import select
    from db.models import Employee
    if actor.kind == "user":
        return select(Employee.id).where(Employee.user_id == actor.id)
    return select(Employee.id).where(Employee.chatter_id == actor.id, Employee.is_active.is_(True))


# Bound to the REPORTER, never the Creator a row names: a shared or transferred Creator would leak one Agency's reports to another.
def _errors_where(actor, is_master: bool, *, since_hours: int | None, source: str | None) -> list:
    from db.models import AppError
    conds = []
    if since_hours is not None:
        conds.append(AppError.occurred_at >= datetime.utcnow() - timedelta(hours=since_hours))
    if source:
        conds.append(AppError.source == source)
    if not is_master:
        conds.append(AppError.employee_id.in_(_employee_ids_of(actor)))
    return conds


def _principal():
    from fastapi import HTTPException
    from auth import get_request_user
    from chatters import current_actor
    actor = current_actor()
    if actor is None:
        raise HTTPException(status_code=401, detail="sign in required")
    user = get_request_user()
    return actor, bool(user is not None and user.is_admin)


def header_attribution(request: Request) -> tuple[str | None, int | None]:
    try:
        employee_id = int(request.headers.get("x-employee-id") or "") or None
    except ValueError:
        employee_id = None
    return request.headers.get("x-account-id") or None, employee_id


# Out-of-reach Creator/Employee is dropped so no session can file a row into another Agency's list.
async def owned_attribution(
    account_id: str | None, employee_id: int | None,
) -> tuple[str | None, int | None]:
    from auth import get_request_user
    from chatters import current_actor, get_request_chatter
    from db.engine import get_session
    from db.models import Employee
    import employees
    actor = current_actor()
    if actor is None:
        return None, None
    user = get_request_user()
    if account_id is not None and account_id not in actor.account_ids:
        account_id = None
    if employee_id is not None and not (user is not None and user.is_admin):
        async with get_session() as s:
            mine = (await s.execute(_employee_ids_of(actor).where(Employee.id == employee_id))).first()
        employee_id = employee_id if mine else None
    if employee_id is None and user is not None:
        employee_id = await employees.get_owner_employee_id(user)
    elif employee_id is None:
        chatter = get_request_chatter()
        owners = sorted(chatter.owner_user_ids) if chatter is not None else []
        if len(owners) == 1:
            async with get_session() as s:
                employee_id = await employees.mirror_id(s, chatter.id, owners[0])
    return (account_id[:64] if account_id else None), employee_id


@router.post("/admin/errors")
async def admin_errors_create(request: Request, body: _AppErrorBody = Body(...)) -> dict[str, Any]:
    """Persist a single error report under the reporter's own Creator/Employee
    (`owned_attribution`). Never raises — if we can't write we still 200 so the
    reporter loop doesn't error-on-error."""
    from db.engine import get_session
    from db.models import AppError
    # The Master reads every row: no pool proxy secrets in it.
    scrub = proxy_registry.scrub_pool_secrets
    try:
        h_account, h_employee = header_attribution(request)
        account_id, employee_id = await owned_attribution(
            body.account_id or h_account, body.employee_id if body.employee_id is not None else h_employee)
        async with get_session() as s:
            row = AppError(
                source=(body.source or "browser")[:32],
                kind=(body.kind or "error")[:64],
                message=scrub(body.message or "")[:4096],
                stack=scrub(body.stack)[:16384] if body.stack else None,
                url=scrub(body.url)[:1024] if body.url else None,
                account_id=account_id,
                employee_id=employee_id,
                user_agent=body.user_agent[:512] if body.user_agent else None,
                context_json=_app_error_context_json(scrub(json.dumps(body.context))) if body.context else None,
            )
            s.add(row)
            await s.commit()
            return {"ok": True, "id": row.id}
    except Exception:
        log.exception("failed to persist app_error")
        return {"ok": False}


_ERRORS_OWNER_ONLY = "owner-only — chatter sessions cannot clear the error log"


@router.delete("/admin/errors")
async def admin_errors_clear(
    since_hours: int | None = Query(None, ge=1, le=720, description="Only clear rows within this window; omit to clear all"),
    source: str | None = Query(None, description="Filter by 'browser' or 'server'"),
) -> dict[str, Any]:
    """Dismiss errors — used by the TopNav badge's Clear button. Owner-only
    (`owner_context`: a chatter session 403s). Deletes only the rows the
    caller's GET shows (`_errors_where`), matching its filter so the badge
    count drops to zero immediately."""
    from agency_context import owner_context
    from db.engine import get_session
    from db.models import AppError
    from sqlalchemy import delete as sa_delete
    await owner_context(None, _ERRORS_OWNER_ONLY)
    actor, is_master = _principal()
    stmt = sa_delete(AppError).where(*_errors_where(actor, is_master, since_hours=since_hours, source=source))
    async with get_session() as s:
        result = await s.execute(stmt.execution_options(synchronize_session=False))
        await s.commit()
        return {"ok": True, "deleted": result.rowcount or 0}


@router.get("/admin/errors")
async def admin_errors_list(
    limit: int = Query(50, ge=1, le=500),
    since_hours: int = Query(24, ge=1, le=720),
    source: str | None = Query(None, description="Filter by 'browser' or 'server'"),
) -> dict[str, Any]:
    """Recent errors the caller may see (`_errors_where`), newest first.
    `since_hours` defaults to 24h so the TopNav badge can count today's errors
    cheaply; `count` is every matching row, `list` at most `limit` of them."""
    from db.engine import get_session
    from db.models import AppError
    from sqlalchemy import func, select
    actor, is_master = _principal()
    conds = _errors_where(actor, is_master, since_hours=since_hours, source=source)
    async with get_session() as s:
        total = (await s.execute(select(func.count(AppError.id)).where(*conds))).scalar_one()
        stmt = select(AppError).where(*conds).order_by(AppError.occurred_at.desc()).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
        return {
            "count": total,
            "since_hours": since_hours,
            "list": [
                {
                    "id": r.id,
                    "occurred_at": r.occurred_at.isoformat() + "Z",
                    "source": r.source,
                    "kind": r.kind,
                    "message": r.message,
                    "stack": r.stack,
                    "url": r.url,
                    "account_id": r.account_id,
                    "employee_id": r.employee_id,
                    "user_agent": r.user_agent,
                    "context": _app_error_context(r.context_json),
                }
                for r in rows
            ],
        }



_PERFLOG_RETAIN_S = int(os.environ.get("PERFLOG_RETAIN_S", str(7 * 24 * 60 * 60)))
_PERFLOG_EVICT_INTERVAL_S = 60 * 60
_PERFLOG_BATCH_MAX = 500
_PERFLOG_META_MAX_BYTES = 4 * 1024


class _PerfLogEventBody(BaseModel):
    opId: str
    kind: str
    phase: str
    ts: float
    tabId: str | None = None
    meta: dict[str, Any] | None = None


class _PerfLogIngestBody(BaseModel):
    tabId: str
    parentTabId: str | None = None
    employeeId: int | None = None
    accountId: str | None = None
    events: list[_PerfLogEventBody]


@router.post("/admin/perflog/ingest")
async def admin_perflog_ingest(request: Request, body: _PerfLogIngestBody = Body(...)) -> dict[str, Any]:
    """Persist a batch of client-side perf events. Never raises — if we
    can't write we still 200 so the client's flush loop doesn't error-on-
    error. Sent via `navigator.sendBeacon` on page unload, plain
    `fetch(..., keepalive: true)` otherwise.

    Soft-tags rows with the requesting employee + account from headers
    when the body didn't carry them, so analytics queries can filter on
    "who's been seeing slow loads"."""
    from db.engine import get_session
    from db.models import PerfEventRow

    if not body.events:
        return {"ok": True, "inserted": 0}
    events = body.events[:_PERFLOG_BATCH_MAX]

    hdr_employee_raw = request.headers.get("x-employee-id")
    try:
        hdr_employee_id: int | None = int(hdr_employee_raw) if hdr_employee_raw else None
    except ValueError:
        hdr_employee_id = None
    hdr_account_id = request.headers.get("x-account-id") or None

    employee_id = body.employeeId if body.employeeId is not None else hdr_employee_id
    account_id = body.accountId if body.accountId else hdr_account_id

    try:
        async with get_session() as s:
            for e in events:
                meta_str: str | None = None
                if e.meta is not None:
                    try:
                        meta_str = json.dumps(e.meta, default=str)[:_PERFLOG_META_MAX_BYTES]
                    except (TypeError, ValueError):
                        meta_str = None
                tab_id = (e.tabId or body.tabId)[:64]
                s.add(PerfEventRow(
                    tab_id=tab_id,
                    parent_tab_id=body.parentTabId[:64] if body.parentTabId else None,
                    op_id=(e.opId or "")[:128],
                    kind=(e.kind or "")[:64],
                    phase=(e.phase or "")[:32],
                    client_ts_ms=int(e.ts),
                    employee_id=employee_id,
                    account_id=account_id[:64] if account_id else None,
                    meta_json=meta_str,
                ))
            await s.commit()
        return {"ok": True, "inserted": len(events)}
    except Exception:
        log.exception("perflog ingest failed")
        return {"ok": False}


@router.get("/admin/perflog/recent")
async def admin_perflog_recent(
    limit: int = Query(200, ge=1, le=2000),
    since_minutes: int = Query(60, ge=1, le=24 * 60 * 7),
    kind: str | None = Query(None, description="Filter by event kind (exact match)"),
    tab_id: str | None = Query(None, description="Filter to a single tab session"),
    op_id: str | None = Query(None, description="Filter to a single op id (all phases)"),
) -> dict[str, Any]:
    """Recent perfLog events, newest first. Powers ad-hoc inspection of
    timing across chatters — e.g. histogram of `vault.media` request→
    delivered deltas, or per-tab "open → first useful paint" times. Every
    Agency's rows, so the Master's alone (`auth.require_master`)."""
    from auth import require_master
    require_master()
    from db.engine import get_session
    from db.models import PerfEventRow
    from sqlalchemy import select

    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
    async with get_session() as s:
        stmt = select(PerfEventRow).where(PerfEventRow.received_at >= cutoff)
        if kind:
            stmt = stmt.where(PerfEventRow.kind == kind)
        if tab_id:
            stmt = stmt.where(PerfEventRow.tab_id == tab_id)
        if op_id:
            stmt = stmt.where(PerfEventRow.op_id == op_id)
        stmt = stmt.order_by(PerfEventRow.received_at.desc()).limit(limit)
        rows = (await s.execute(stmt)).scalars().all()
        return {
            "count": len(rows),
            "since_minutes": since_minutes,
            "list": [
                {
                    "id": r.id,
                    "tab_id": r.tab_id,
                    "parent_tab_id": r.parent_tab_id,
                    "op_id": r.op_id,
                    "kind": r.kind,
                    "phase": r.phase,
                    "client_ts_ms": r.client_ts_ms,
                    "received_at": r.received_at.isoformat() + "Z",
                    "employee_id": r.employee_id,
                    "account_id": r.account_id,
                    "meta": json.loads(r.meta_json) if r.meta_json else None,
                }
                for r in rows
            ],
        }


async def _perflog_sweep() -> None:
    from db.engine import get_session
    from db.models import PerfEventRow
    from sqlalchemy import delete as sa_delete
    cutoff = datetime.utcnow() - timedelta(seconds=_PERFLOG_RETAIN_S)
    async with get_session() as s:
        res = await s.execute(
            sa_delete(PerfEventRow).where(PerfEventRow.received_at < cutoff)
        )
        await s.commit()
        if (res.rowcount or 0) > 0:
            log.info("perflog evictor pruned %d rows (retain=%ds)", res.rowcount, _PERFLOG_RETAIN_S)


async def _perflog_evictor_loop() -> None:
    await relay_host.periodic("perflog evictor", _PERFLOG_EVICT_INTERVAL_S, _perflog_sweep)
