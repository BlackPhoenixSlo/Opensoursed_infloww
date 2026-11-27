from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import settings_api
from auth import get_request_user
from chatters import get_request_chatter
from db.engine import get_session
from db.models import User
from support_hub import MAX_TEXT

log = logging.getLogger("of-relay.support_api")

router = APIRouter()

UNREAD_TTL_S = 30.0
TIMEOUT = httpx.Timeout(6.0, connect=3.0)
NOT_CONFIGURED = {"configured": False}

_unread: dict[str, tuple[float, int]] = {}
_transport: httpx.AsyncBaseTransport | None = None
_clock = time.monotonic


@dataclass(frozen=True)
class Hub:
    url: str
    token: str
    instance: str


def _hub_config() -> Hub | None:
    url = os.environ.get("SUPPORT_HUB_URL", "").strip().rstrip("/")
    token = os.environ.get("SUPPORT_HUB_TOKEN", "").strip()
    if not url or not token:
        return None
    return Hub(url, token, os.environ.get("SUPPORT_INSTANCE", "").strip() or "instance")


@dataclass(frozen=True)
class Asker:
    user_key: str
    name: str
    role: str
    agency_id: str
    agency_name: str


async def _agency_name(agency_id: str) -> str:
    if not agency_id:
        return ""
    try:
        async with get_session() as s:
            name = (await settings_api.applied_blob(s, agency_id, "account")).get("agency_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
            return await s.scalar(select(User.username).where(User.id == agency_id)) or ""
    except Exception:
        log.warning("support: agency name read failed agency=%s", agency_id, exc_info=True)
        return ""


async def _asker() -> Asker:
    user = get_request_user()
    if user is not None:
        agency_id, who = user.id, f"u:{user.id}"
        name, role = user.username, "master" if user.is_admin else "owner"
    else:
        chatter = get_request_chatter()
        if chatter is None:
            raise HTTPException(status_code=401, detail="sign in required")
        agency_id = min(chatter.owner_user_ids) if chatter.owner_user_ids else ""
        who = f"c:{chatter.id}"
        name, role = chatter.display_name or chatter.username, "chatter"
    return Asker(f"{agency_id}:{who}", name, role, agency_id, await _agency_name(agency_id))


async def _call(hub: Hub, method: str, path: str, *, json: dict | None = None,
                params: dict | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=_transport) as client:
            r = await client.request(method, f"{hub.url}/support/api/instance/{path}", json=json,
                                     params=params, headers={"Authorization": f"Bearer {hub.token}"})
    except httpx.HTTPError as e:
        log.warning("support: hub %s %s failed: %s", method, path, type(e).__name__)
        raise HTTPException(status_code=502, detail="Support is unreachable right now — try again soon.")
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="You've sent a lot of messages — wait a few minutes, then try again.")
    if r.status_code != 200:
        log.warning("support: hub %s %s answered %s", method, path, r.status_code)
        raise HTTPException(status_code=502, detail="Support is unreachable right now — try again soon.")
    return r.json()


def _who(hub: Hub, asker: Asker) -> dict[str, str]:
    return {"instance": hub.instance, "user_key": asker.user_key}


def _messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": m["id"], "from": "support" if m["sender"] == "support" else "me",
             "text": m["text"], "at": m["at"]} for m in body.get("messages", [])]


@router.get("/admin/support/unread")
async def unread() -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    cached = _unread.get(asker.user_key)
    now = _clock()
    if cached is not None and now - cached[0] < UNREAD_TTL_S:
        return {"configured": True, "unread": cached[1]}
    try:
        n = int((await _call(hub, "GET", "unread", params=_who(hub, asker))).get("unread") or 0)
    except HTTPException:
        return {"configured": True, "unread": 0}
    _unread[asker.user_key] = (now, n)
    return {"configured": True, "unread": n}


@router.get("/admin/support/thread")
async def thread() -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    return {"configured": True,
            "messages": _messages(await _call(hub, "GET", "thread", params=_who(hub, asker)))}


class SendBody(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT)


@router.post("/admin/support/messages")
async def send(body: SendBody = Body(...)) -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty message")
    payload = {**_who(hub, asker), "agency_id": asker.agency_id, "agency_name": asker.agency_name,
               "name": asker.name, "role": asker.role, "text": text}
    return {"configured": True, "messages": _messages(await _call(hub, "POST", "messages", json=payload))}


@router.post("/admin/support/read")
async def mark_read() -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    await _call(hub, "POST", "read", json=_who(hub, asker))
    _unread[asker.user_key] = (_clock(), 0)
    return {"configured": True, "ok": True}
