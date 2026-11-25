from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select, update

from db.engine import get_session
from db.models import Employee, EmployeeGroup
from employees import AgencyContext, json_object, owner_context

router = APIRouter(prefix="/admin/employee-groups", tags=["employee-groups"])

MAX_NAME = 64
_OWNER_ONLY = "only the agency owner manages Employee groups"


async def _owner_context() -> AgencyContext:
    return await owner_context(None, _OWNER_ONLY)


def _out(g: EmployeeGroup, employee_count: int) -> dict[str, Any]:
    return {"id": g.id, "name": g.name, "parent_id": g.parent_id, "employee_count": employee_count}


async def _own_group(s, agency_user_id: str, group_id: int) -> EmployeeGroup:
    g = await s.get(EmployeeGroup, group_id)
    if g is None or g.agency_user_id != agency_user_id:
        raise HTTPException(status_code=404, detail=f"no group with id {group_id}")
    return g


@router.get("")
async def list_groups() -> dict[str, Any]:
    ctx = await _owner_context()
    async with get_session() as s:
        groups = (await s.execute(
            select(EmployeeGroup).where(EmployeeGroup.agency_user_id == ctx.agency_user_id)
            .order_by(EmployeeGroup.id)
        )).scalars().all()
        counts = dict((await s.execute(
            select(Employee.group_id, func.count())
            .where(Employee.user_id == ctx.agency_user_id, Employee.group_id.isnot(None))
            .group_by(Employee.group_id)
        )).all())
        return {"groups": [_out(g, counts.get(g.id, 0)) for g in groups]}


def _name(value: Any) -> str:
    if not isinstance(value, str) or not (1 <= len(value.strip()) <= MAX_NAME):
        raise HTTPException(status_code=422, detail=f"name must be 1 to {MAX_NAME} characters")
    return value.strip()


def _parent_id(value: Any) -> int | None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise HTTPException(status_code=422, detail="parent_id must be a group id or null")
    return value


async def _refuse_sibling_clash(s, agency_user_id: str, parent_id: int | None, name: str,
                                except_id: int | None = None) -> None:
    parent_match = (EmployeeGroup.parent_id.is_(None) if parent_id is None
                    else EmployeeGroup.parent_id == parent_id)
    q = select(EmployeeGroup.id).where(
        EmployeeGroup.agency_user_id == agency_user_id, parent_match, EmployeeGroup.name == name,
    )
    if except_id is not None:
        q = q.where(EmployeeGroup.id != except_id)
    if (await s.execute(q)).first() is not None:
        raise HTTPException(status_code=409, detail="a group of this name already sits here")


async def _descendants(s, agency_user_id: str, group_id: int) -> set[int]:
    edges = (await s.execute(
        select(EmployeeGroup.id, EmployeeGroup.parent_id).where(EmployeeGroup.agency_user_id == agency_user_id)
    )).all()
    below: set[int] = set()
    frontier = {group_id}
    while frontier:
        frontier = {g for g, parent in edges if parent in frontier and g not in below}
        below |= frontier
    return below


@router.post("")
async def create_group(request: Request) -> dict[str, Any]:
    ctx = await _owner_context()
    body = await json_object(request, 422)
    name = _name(body.get("name"))
    parent_id = _parent_id(body.get("parent_id"))
    async with get_session() as s:
        if parent_id is not None:
            await _own_group(s, ctx.agency_user_id, parent_id)
        await _refuse_sibling_clash(s, ctx.agency_user_id, parent_id, name)
        g = EmployeeGroup(agency_user_id=ctx.agency_user_id, parent_id=parent_id, name=name)
        s.add(g)
        await s.flush()
        return _out(g, 0)


@router.patch("/{group_id}")
async def update_group(group_id: int, request: Request) -> dict[str, Any]:
    """Rename and/or move a group; an absent key keeps its value, `parent_id: null` moves it under the root."""
    ctx = await _owner_context()
    body = await json_object(request, 422)
    if "name" not in body and "parent_id" not in body:
        raise HTTPException(status_code=422, detail="send name and/or parent_id")
    name = _name(body["name"]) if "name" in body else None
    parent_id = _parent_id(body["parent_id"]) if "parent_id" in body else None
    async with get_session() as s:
        g = await _own_group(s, ctx.agency_user_id, group_id)
        if "parent_id" in body and parent_id is not None:
            await _own_group(s, ctx.agency_user_id, parent_id)
            if parent_id == group_id or parent_id in await _descendants(s, ctx.agency_user_id, group_id):
                raise HTTPException(status_code=409, detail="a group cannot move under itself or its own sub-group")
        new_name = name if name is not None else g.name
        new_parent = parent_id if "parent_id" in body else g.parent_id
        await _refuse_sibling_clash(s, ctx.agency_user_id, new_parent, new_name, except_id=group_id)
        g.name, g.parent_id = new_name, new_parent
        await s.flush()
        count = (await s.execute(
            select(func.count()).select_from(Employee).where(Employee.group_id == group_id)
        )).scalar_one()
        return _out(g, count)


@router.delete("/{group_id}")
async def delete_group(group_id: int) -> dict[str, Any]:
    ctx = await _owner_context()
    async with get_session() as s:
        g = await _own_group(s, ctx.agency_user_id, group_id)
        child = (await s.execute(
            select(EmployeeGroup.id).where(EmployeeGroup.parent_id == group_id).limit(1)
        )).first()
        if child is not None:
            raise HTTPException(status_code=409, detail="the group has sub-groups")
        member = (await s.execute(
            select(Employee.id).where(Employee.group_id == group_id).limit(1)
        )).first()
        if member is not None:
            raise HTTPException(status_code=409, detail="the group has Employees")
        await s.delete(g)
        return {"deleted": group_id}


def _ids(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return None
    return list(dict.fromkeys(value))


@router.put("/members")
async def set_members(request: Request) -> dict[str, Any]:
    """Batch edit group: every listed Employee into one group, or none, in one write."""
    ctx = await _owner_context()
    body = await json_object(request, 422)
    group_id = body.get("group_id", ...)
    if group_id is ... or (group_id is not None and (not isinstance(group_id, int) or isinstance(group_id, bool))):
        raise HTTPException(status_code=422, detail="group_id must be a group id or null")
    employee_ids = _ids(body.get("employee_ids"))
    if employee_ids is None:
        raise HTTPException(status_code=422, detail="employee_ids must be a non-empty list of Employee ids")
    async with get_session() as s:
        if group_id is not None:
            await _own_group(s, ctx.agency_user_id, group_id)
        own = set((await s.execute(
            select(Employee.id).where(Employee.id.in_(employee_ids), Employee.user_id == ctx.agency_user_id)
        )).scalars().all())
        if len(own) != len(employee_ids):
            raise HTTPException(status_code=400, detail="every employee must belong to this agency")
        await s.execute(update(Employee).where(Employee.id.in_(employee_ids)).values(group_id=group_id))
        return {"group_id": group_id, "employee_ids": employee_ids}


async def subtree_employee_ids(agency_user_id: str, employee_id: int) -> set[int]:
    async with get_session() as s:
        e = await s.get(Employee, employee_id)
        if e is None or e.user_id != agency_user_id or e.group_id is None:
            return {employee_id}
        below = await _descendants(s, agency_user_id, e.group_id)
        members = set((await s.execute(
            select(Employee.id).where(Employee.user_id == agency_user_id, Employee.group_id.in_(below))
        )).scalars().all()) if below else set()
        return {employee_id} | members
