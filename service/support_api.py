from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

import settings_api
from auth import get_request_user
from chatters import get_request_chatter
from db.engine import get_session
from db.models import User
from support_hub import MAX_FIELD, MAX_TEXT, ReadAck, ReadPosition, SentMessages, ThreadMessages, UnreadCount
from support_photos import PHOTO_HEADERS, capped_form, form_text, read_photos

log = logging.getLogger("of-relay.support_api")

router = APIRouter()

UNREAD_TTL_S = 30.0
TIMEOUT = httpx.Timeout(6.0, connect=3.0)
PHOTO_TIMEOUT = httpx.Timeout(30.0, connect=3.0)
UNREACHABLE = "Support is unreachable right now — try again soon."
NOT_CONFIGURED = {"configured": False}
SEND_LIMIT_DETAIL = "You've sent a lot of messages — wait a few minutes, then try again."

_unread: dict[str, tuple[float, int]] = {}


@dataclass(frozen=True)
class Hub:
    url: str
    token: str
    instance: str


@lru_cache(maxsize=1)
def _secure_hub_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname:
            return True
    except ValueError:
        pass
    log.warning("support: SUPPORT_HUB_URL must use HTTPS")
    return False


def _hub_config() -> Hub | None:
    url = os.environ.get("SUPPORT_HUB_URL", "").strip().rstrip("/")
    token = os.environ.get("SUPPORT_HUB_TOKEN", "").strip()
    if not url or not token or not _secure_hub_url(url):
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


ResponseT = TypeVar("ResponseT", bound=BaseModel)


async def _hub_request(hub: Hub, method: str, path: str, *, timeout: httpx.Timeout, **kw: Any) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(method, f"{hub.url}/support/api/instance/{path}",
                                        headers={"Authorization": f"Bearer {hub.token}"}, **kw)
    except httpx.HTTPError as e:
        log.warning("support: hub %s %s failed: %s", method, path, type(e).__name__)
        raise HTTPException(status_code=502, detail=UNREACHABLE)


def _hub_json(r: httpx.Response, method: str, path: str, response: type[ResponseT], *,
              rate_limit_detail: str | None = None) -> ResponseT:
    if r.status_code == 429 and rate_limit_detail is not None:
        raise HTTPException(status_code=429, detail=rate_limit_detail)
    if r.status_code != 200:
        log.warning("support: hub %s %s answered %s", method, path, r.status_code)
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    try:
        return response.model_validate(r.json(), strict=True)
    except ValueError:
        log.warning("support: hub %s %s failed: InvalidResponse", method, path)
        raise HTTPException(status_code=502, detail=UNREACHABLE)


async def _call(hub: Hub, method: str, path: str, response: type[ResponseT], *,
                json: dict | None = None, params: dict | None = None, rate_limit_detail: str | None = None) -> ResponseT:
    r = await _hub_request(hub, method, path, timeout=TIMEOUT, json=json, params=params)
    return _hub_json(r, method, path, response, rate_limit_detail=rate_limit_detail)


def _who(hub: Hub, asker: Asker) -> dict[str, str]:
    return {"instance": hub.instance, "user_key": asker.user_key}


def _messages(body: ThreadMessages) -> list[dict[str, Any]]:
    return [{"id": m.id, "from": "support" if m.sender == "support" else "me",
             "text": m.text, "at": m.at, "photos": [p.model_dump() for p in m.photos]} for m in body.messages]


@router.get("/admin/support/unread")
async def unread() -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    cached = _unread.get(asker.user_key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < UNREAD_TTL_S:
        return {"configured": True, "unread": cached[1]}
    try:
        n = (await _call(hub, "GET", "unread", UnreadCount, params=_who(hub, asker))).unread
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
            "messages": _messages(await _call(hub, "GET", "thread", ThreadMessages, params=_who(hub, asker)))}


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
    payload = {**_who(hub, asker), "agency_id": asker.agency_id, "agency_name": asker.agency_name[:MAX_FIELD],
               "name": asker.name[:MAX_FIELD], "role": asker.role, "text": text}
    response = await _call(hub, "POST", "messages", SentMessages, json=payload,
                           rate_limit_detail=SEND_LIMIT_DETAIL)
    return {"configured": True, "messages": _messages(response)}


@router.post("/admin/support/messages/upload")
async def send_upload(request: Request) -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    form = await capped_form(request, max_fields=1)
    try:
        text = form_text(form, "text", MAX_TEXT).strip()
        photos = await read_photos(form)
    finally:
        await form.close()
    if not text and not photos:
        raise HTTPException(status_code=400, detail="empty message")
    fields = {**_who(hub, asker), "agency_id": asker.agency_id, "agency_name": asker.agency_name[:MAX_FIELD],
              "name": asker.name[:MAX_FIELD], "role": asker.role, "text": text}
    r = await _hub_request(hub, "POST", "messages/upload", timeout=PHOTO_TIMEOUT, data=fields,
                           files=[("photos", (f"photo{i}.jpg", p, "image/jpeg")) for i, p in enumerate(photos)])
    if r.status_code in (400, 413, 507):
        try:
            body = r.json()
        except ValueError:
            body = None
        detail = body.get("detail") if isinstance(body, dict) else None
        raise HTTPException(status_code=r.status_code, detail=detail if isinstance(detail, str) else "Couldn't send that.")
    response = _hub_json(r, "POST", "messages/upload", SentMessages, rate_limit_detail=SEND_LIMIT_DETAIL)
    return {"configured": True, "messages": _messages(response)}


@router.get("/admin/support/photos/{photo_id}")
async def photo(photo_id: int) -> Response:
    hub = _hub_config()
    if hub is None:
        raise HTTPException(status_code=404, detail="Not Found")
    asker = await _asker()
    r = await _hub_request(hub, "GET", f"photos/{photo_id}", timeout=PHOTO_TIMEOUT, params=_who(hub, asker))
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="no such photo")
    if r.status_code != 200:
        log.warning("support: hub GET photos answered %s", r.status_code)
        raise HTTPException(status_code=502, detail=UNREACHABLE)
    return Response(r.content, media_type="image/jpeg", headers=PHOTO_HEADERS)


@router.post("/admin/support/read")
async def mark_read(body: ReadPosition = Body(...)) -> dict[str, Any]:
    hub = _hub_config()
    if hub is None:
        return NOT_CONFIGURED
    asker = await _asker()
    await _call(hub, "POST", "read", ReadAck, json={**_who(hub, asker), "up_to": body.up_to})
    _unread.pop(asker.user_key, None)
    return {"configured": True, "ok": True}
