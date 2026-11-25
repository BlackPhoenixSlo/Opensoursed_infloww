from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

import platforms
import push_decide as pd
import push_send
from db.engine import get_session
from db.models import PushSubscription

router = APIRouter(prefix="/push", tags=["push"])

MAX_PER_PRINCIPAL = 10
RATE_PUT = 20
TYPE_KEYS = frozenset({"message", "purchases", "tip", "subscribed", "commented", "mentioned", "favorited"})
_puts: dict[tuple[str, str], deque] = {}


def _cookie_principals(request: Request) -> list[tuple[str, str, int]]:
    import auth
    import chatters
    out = []
    for kind, name, parse in (("user", auth.COOKIE_NAME, auth.parse_cookie_issued),
                              ("chatter", chatters.COOKIE_NAME, chatters.parse_cookie_issued)):
        raw = request.cookies.get(name)
        parsed = parse(raw) if raw else None
        if parsed:
            out.append((kind, parsed[0], int(parsed[1])))
    return out


def _principal(request: Request) -> tuple[str, str, int]:
    import auth
    import chatters
    if auth.get_impersonation() is not None:
        raise HTTPException(status_code=403, detail="push is off while impersonating")
    actor = chatters.current_actor()
    if actor is None:
        raise HTTPException(status_code=401, detail="sign in required")
    for kind, pid, issued in _cookie_principals(request):
        if kind == actor.kind and pid == actor.id:
            return kind, pid, issued
    raise HTTPException(status_code=401, detail="sign in required")


def _own(sub_id: str, kind: str, pid: str) -> push_send.Sub:
    sub = push_send.owned(sub_id, kind, pid)
    if sub is None:
        raise HTTPException(status_code=404, detail="no such subscription")
    return sub


def _rate(kind: str, pid: str) -> None:
    now = time.monotonic()
    q = _puts.setdefault((kind, pid), deque())
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PUT:
        raise HTTPException(status_code=429, detail="too many subscription updates")
    q.append(now)
    if len(_puts) > 10_000:
        _puts.clear()


def _live() -> None:
    if push_send.disabled():
        raise HTTPException(status_code=503, detail={"reason": push_send.disabled()})


def _key_ok(s: str, n: int) -> bool:
    try:
        return len(push_send.b64d(s)) == n
    except (ValueError, TypeError):
        return False


@router.get("/key")
def get_key(request: Request) -> dict:
    _principal(request)
    _live()
    return {"key": push_send.public_key()}


class _Keys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=pd.KEY_MAX)
    auth: str = Field(..., min_length=1, max_length=pd.KEY_MAX)


class _SubBody(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=pd.ENDPOINT_MAX)
    keys: _Keys
    types: list[str] = Field(default_factory=list, max_length=32)
    platforms: dict[str, bool] = Field(default_factory=dict)


@router.put("/subscription")
async def put_subscription(request: Request, body: _SubBody = Body(...)) -> dict:
    kind, pid, issued = _principal(request)
    _live()
    if not pd.endpoint_allowed(body.endpoint, push_send.HOSTS):
        raise HTTPException(status_code=400, detail="push endpoint not allowed")
    if not (_key_ok(body.keys.p256dh, 65) and _key_ok(body.keys.auth, 16)):
        raise HTTPException(status_code=400, detail="bad subscription keys")
    _rate(kind, pid)
    return {"id": await _save(kind, pid, issued, body)}


async def _save(kind: str, pid: str, issued: int, body: _SubBody) -> str:
    try:
        sub, evicted = await _store(kind, pid, issued, body)
    except IntegrityError:
        sub, evicted = await _store(kind, pid, issued, body)
    for sid in evicted:
        push_send.forget(sid)
    push_send.upsert(sub)
    return sub.id


async def _store(kind: str, pid: str, issued: int, body: _SubBody) -> tuple[push_send.Sub, list[str]]:
    types = json.dumps(sorted(set(body.types) & TYPE_KEYS))
    prefs = json.dumps({k: bool(v) for k, v in body.platforms.items() if k in platforms.KEYS})
    now = datetime.utcnow()
    async with get_session() as s:
        row = (await s.execute(select(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint))).scalar_one_or_none()
        if row is None:
            row = PushSubscription(id=uuid.uuid4().hex, endpoint=body.endpoint, created_at=now)
            s.add(row)
        elif (row.principal_kind, row.principal_id) != (kind, pid) and (
                row.p256dh, row.auth) != (body.keys.p256dh, body.keys.auth):
            raise HTTPException(status_code=409, detail="endpoint bound to another session")
        row.p256dh, row.auth = body.keys.p256dh, body.keys.auth
        row.principal_kind, row.principal_id, row.issued_ms = kind, pid, issued
        row.types, row.platforms, row.updated_at = types, prefs, now
        await s.flush()
        mine = (await s.execute(select(PushSubscription).where(
            PushSubscription.principal_kind == kind, PushSubscription.principal_id == pid,
        ).order_by(PushSubscription.updated_at.desc(), PushSubscription.created_at.desc()))).scalars().all()
        evicted = [r.id for r in mine[MAX_PER_PRINCIPAL:] if r.id != row.id]
        if evicted:
            await s.execute(delete(PushSubscription).where(PushSubscription.id.in_(evicted)))
        return push_send.sub_from_row(row), evicted


class _DelBody(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=pd.ENDPOINT_MAX)


@router.delete("/subscription")
async def delete_subscription(request: Request, body: _DelBody = Body(...)) -> dict:
    kind, pid, _ = _principal(request)
    async with get_session() as s:
        ids = (await s.execute(select(PushSubscription.id).where(
            PushSubscription.endpoint == body.endpoint, PushSubscription.principal_kind == kind,
            PushSubscription.principal_id == pid))).scalars().all()
        if ids:
            await s.execute(delete(PushSubscription).where(PushSubscription.id.in_(ids)))
    for sid in ids:
        push_send.forget(sid)
    return {"deleted": len(ids)}


class _TestBody(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    delay_s: float = Field(0, ge=0, le=15)


@router.post("/test")
async def post_test(request: Request, body: _TestBody = Body(...)) -> dict:
    kind, pid, _ = _principal(request)
    _live()
    _own(body.id, kind, pid)
    return await push_send.send_test(body.id, body.delay_s)


async def forget_cookies(request: Request) -> int:
    n = 0
    try:
        for kind, pid, issued in _cookie_principals(request):
            async with get_session() as s:
                ids = (await s.execute(select(PushSubscription.id).where(
                    PushSubscription.principal_kind == kind, PushSubscription.principal_id == pid,
                    PushSubscription.issued_ms == issued))).scalars().all()
                if ids:
                    await s.execute(delete(PushSubscription).where(PushSubscription.id.in_(ids)))
            for sid in ids:
                push_send.forget(sid)
            n += len(ids)
    except Exception:
        import logging
        logging.getLogger("of-relay.push").exception("push forget on logout failed")
    return n
