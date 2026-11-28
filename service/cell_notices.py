from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Header
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import cell_mode
from agency_copy import caller
from db.engine import get_session
from db.models import AgencyNotification, Employee, User
from notifications_api import PINNED_KIND, RETENTION, push_unread

log = logging.getLogger(__name__)
router = APIRouter()

TICK_S = 2.0
BATCH = 200
CALL_TIMEOUT_S = 10.0
# A day short of Control's retention so a replay never re-files a row Control's tick just aged out.
CUTOFF = RETENTION - timedelta(days=1)


async def _outbox(after: int, anchor: tuple[int, datetime] | None) -> tuple[int, list, list]:
    async with get_session() as s:
        # ids are not AUTOINCREMENT: a deleted top row's id is reused, so a moved anchor means replay.
        if anchor is not None and await s.scalar(
                select(AgencyNotification.created_at).where(AgencyNotification.id == anchor[0])) != anchor[1]:
            after = 0
        rows = (await s.execute(select(AgencyNotification).where(
            AgencyNotification.id > after, AgencyNotification.created_at > datetime.utcnow() - CUTOFF)
            .order_by(AgencyNotification.id).limit(BATCH))).scalars().all()
        # Read after the rows: a pin filed in between is then in the snapshot, never deleted on Control unsent.
        pins = sorted(set((await s.execute(select(AgencyNotification.agency_user_id, AgencyNotification.account_id)
                                           .where(AgencyNotification.kind == PINNED_KIND))).all()))
    return after, list(rows), pins


def _wire(n: AgencyNotification, platform: str | None) -> dict[str, Any]:
    return {"id": n.id, "agency_user_id": n.agency_user_id, "kind": n.kind, "text": n.text, "platform": platform,
            "account_id": n.account_id, "employee_id": n.employee_id, "data_json": n.data_json,
            "dedupe_key": n.dedupe_key, "created_at": n.created_at.isoformat()}


async def forward_forever() -> None:
    import httpx
    url = os.environ["OI_CELL_CONTROL_URL"].rstrip("/") + "/fleet/notices"
    headers = {"Authorization": f"Bearer {os.environ.get('OI_CELL_COPY_KEY', '')}"}
    cursor, anchor, sent_pins, down_since = 0, None, None, None
    async with httpx.AsyncClient(timeout=CALL_TIMEOUT_S, headers=headers) as client:
        while True:
            more = False
            try:
                after, rows, pins = await _outbox(cursor, anchor)
                if after != cursor:
                    cursor, anchor = after, None
                if rows or pins != sent_pins:
                    plat = cell_mode._owned_platforms()
                    send = [_wire(n, plat.get(n.account_id)) for n in rows if n.account_id is None or n.account_id in plat]
                    if len(send) < len(rows):
                        log.warning("Cells: %d bell notice(s) name a Creator this Cell no longer owns; not sent",
                                    len(rows) - len(send))
                    r = await client.post(url, json={"rows": send,
                                                     "pinned": [[u, plat[a], a] for u, a in pins if a in plat]})
                    r.raise_for_status()
                    if rows:
                        cursor, anchor = rows[-1].id, (rows[-1].id, rows[-1].created_at)
                    sent_pins, more = pins, len(rows) == BATCH
                if down_since is not None:
                    log.warning("Cells: bell notices reach Control again after %.0f s", time.monotonic() - down_since)
                    down_since = None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if down_since is None:
                    down_since = time.monotonic()
                    log.error("Cells: bell notices not delivered to Control (%s: %s); kept on this Cell, retrying"
                              " every %.0f s", type(e).__name__, e, TICK_S)
            if not more:
                await asyncio.sleep(TICK_S)


def _stamp(raw: object) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _row(cell: str, r: object, mine) -> dict[str, Any] | None:
    if not isinstance(r, dict):
        return None
    rid, user, kind, text, aid = r.get("id"), r.get("agency_user_id"), r.get("kind"), r.get("text"), r.get("account_id")
    at = _stamp(r.get("created_at"))
    if (not isinstance(rid, int) or not isinstance(user, str) or not isinstance(kind, str) or not isinstance(text, str)
            or at is None or (aid is not None and not mine(r.get("platform"), aid))):
        return None
    emp, data, key = r.get("employee_id"), r.get("data_json"), r.get("dedupe_key")
    return dict(agency_user_id=user, kind=kind, text=text, account_id=aid,
                employee_id=emp if isinstance(emp, int) else None, data_json=data if isinstance(data, str) else None,
                dedupe_key=key if isinstance(key, str) and key else f"cell:{cell}:{rid}:{at.isoformat()}",
                created_at=at)


@router.post("/fleet/notices")
async def take(body: Annotated[dict, Body()], authorization: Annotated[str | None, Header()] = None):
    cell = caller(authorization)
    if cell is None:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    try:
        placed = {k: c for k, c in cell_mode.read_placement()["accounts"].items() if c == cell}
    except (KeyError, OSError, ValueError, AttributeError, TypeError):
        return JSONResponse({"detail": {"error": "placement_unavailable"}}, status_code=503)

    def mine(platform: object, aid: object) -> bool:
        return isinstance(platform, str) and isinstance(aid, str) and f"{platform}:{aid}" in placed

    raw = body.get("rows") if isinstance(body.get("rows"), list) else []
    rows = [v for v in (_row(cell, r, mine) for r in raw) if v is not None]
    pinned = {(p[0], p[2]) for p in body.get("pinned") or []
              if isinstance(p, list) and len(p) == 3 and isinstance(p[0], str) and mine(p[1], p[2])}
    filed: set[str] = set()
    n = 0
    async with get_session() as s:
        users = set((await s.execute(select(User.id).where(
            User.id.in_({v["agency_user_id"] for v in rows})))).scalars().all())
        emps = set((await s.execute(select(Employee.id).where(
            Employee.id.in_({v["employee_id"] for v in rows if v["employee_id"] is not None})))).scalars().all())
        kept = [v for v in rows if v["agency_user_id"] in users]
        for v in kept:
            if v["employee_id"] not in emps:
                v["employee_id"] = None
            if (await s.execute(sqlite_insert(AgencyNotification).values(v).on_conflict_do_nothing())).rowcount:
                filed.add(v["agency_user_id"])
                n += 1
        held = (await s.execute(select(AgencyNotification.id, AgencyNotification.agency_user_id,
                                       AgencyNotification.account_id).where(
            AgencyNotification.kind == PINNED_KIND,
            AgencyNotification.account_id.in_({k.partition(":")[2] for k in placed})))).all()
        gone = [(i, u) for i, u, a in held if (u, a) not in pinned]
        if gone:
            await s.execute(delete(AgencyNotification).where(AgencyNotification.id.in_([i for i, _ in gone])))
    skipped = len(raw) - len(kept)
    if skipped:
        log.warning("Cells: %d bell notice(s) from %s skipped (malformed, unknown owner or not its Creator)",
                    skipped, cell)
    await push_unread(sorted(filed | {u for _, u in gone}))
    return {"filed": n, "dropped": len(gone), "skipped": skipped}
