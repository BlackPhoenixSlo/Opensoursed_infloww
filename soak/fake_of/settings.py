from __future__ import annotations

import copy
import json
import re
import struct
import time
import zlib
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from soak.fake_of import posts, render, vault

_STATE = "_soak_settings"
DIGEST = "new_likes_digest"
DIGEST_HOURS = 12
# OF draws the email list and select only with the master Email switch on, so the fake account starts with it on
EMAIL_MASTER = "isEmailNotificationsEnabled"
COUNTRIES = [{"id": i, "code": code, "name": name} for i, (code, name) in enumerate((
    ("BV", "Bouvet Island"), ("DE", "Germany"), ("GB", "United Kingdom"), ("TV", "Tuvalu"),
    ("US", "United States of America")), 1)]


def _state(fake) -> dict[str, Any]:
    st = fake.__dict__.get(_STATE)
    if st is None:
        st = fake.__dict__[_STATE] = {"settings": copy.deepcopy(render.fixture("settings-settings.json")),
                                      "notifications": {},
                                      "profile": {"avatar": None, "header": picture_url(PRIOR_COVER), "about": None,
                                                  "pending": {}}}
        st["settings"][EMAIL_MASTER] = True
    return st


def email_off(fake) -> None:
    settings(fake)[EMAIL_MASTER] = False
    for x in _items(notifications(fake, "email") or []):
        if x.get("code") == DIGEST:
            x.update(isEnabled=False, value=0)


def settings(fake) -> dict[str, Any]:
    return _state(fake)["settings"]


PICTURES = ("avatar", "header")
PRIOR_COVER = "soak-prior-cover"
PRIOR_COVER_PNG = vault._png(12)
_PROFILE_FILE = re.compile(r"/cdn/files/soak/profile/([^/]+)\.png")
# ASSUMPTION: live OF shows a saved upload late (measured) but the delay is not; 3 s sits under the driver's 6 s quiet wait and 60 s after-undo wait
STALE_S = 3.0
_clock = time.monotonic
_NOTE = b"soak re-encode"


# live OF re-encodes a saved upload (measured: other bytes, same pixels), so compare pixels, not sha256
def reencode(data: bytes) -> bytes:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        body = b"tEXt" + b"Comment\x00" + _NOTE
        chunk = struct.pack(">I", len(body) - 4) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return data[:33] + chunk + data[33:]
    if data.startswith(b"\xff\xd8"):
        return data[:2] + b"\xff\xfe" + struct.pack(">H", len(_NOTE) + 2) + _NOTE + data[2:]
    return data


def picture_url(process_id: str) -> str:
    return f"https://{vault.CDN_HOST}/files/soak/profile/{process_id}.png"


async def cdn(fake, req: Request) -> Response:
    """The fake's /cdn: a profile picture as its bytes (PRIOR_COVER_PNG, or what the upload behind its processId
    stored; unknown: 404), anything else the vault's placeholder."""
    m = _PROFILE_FILE.fullmatch(req.url.path)
    if m is None:
        return await vault.cdn(fake, req)
    data = PRIOR_COVER_PNG if m[1] == PRIOR_COVER else posts.converted(fake).get(m[1])
    if data is not None and m[1] != PRIOR_COVER:
        data = reencode(data)
    if data is None:
        fake._log(req, 404, True)
        return Response(b"", status_code=404)
    fake._log(req, 200, True)
    kind = ("image/jpeg" if data.startswith(b"\xff\xd8") else "image/gif" if data.startswith(b"GIF8")
            else "image/webp" if data[8:12] == b"WEBP" else "image/png")
    return Response(data, media_type=kind)


def profile_overlay(fake, d: dict[str, Any]) -> dict[str, Any]:
    st = _state(fake)["profile"]
    for k, (url, due) in list(st["pending"].items()):
        if _clock() >= due:
            st[k] = url
            del st["pending"][k]
    d.update({k: st[k] for k in PICTURES})
    if st["about"] is not None:
        d["about"] = st["about"]
    return d


def notifications(fake, transport: str) -> list[dict[str, Any]] | None:
    st = _state(fake)["notifications"]
    if transport not in st:
        try:
            st[transport] = copy.deepcopy(render.fixture(f"settings-notifications-{transport}.json"))
        except FileNotFoundError:
            return None
        if transport == "email":
            for x in _items(st[transport]):
                if x.get("code") == DIGEST:
                    x.update(isEnabled=True, value=DIGEST_HOURS)
    return st[transport]


def _items(groups: list[dict[str, Any]]):
    for g in groups:
        yield from g.get("items") or []


async def _body(req: Request) -> Any:
    raw = await req.body()
    return json.loads(raw) if raw else {}


async def _get_settings(fake, req: Request, ok) -> Response:
    return ok(req, settings(fake))


async def _patch_security(fake, req: Request, ok) -> Response:
    body = await _body(req)
    if isinstance(body, dict):
        settings(fake).update(body)
    fake._log(req, 200, True, body)
    return JSONResponse(settings(fake))


async def _put_security(fake, req: Request, ok) -> Response:
    return await _patch_security(fake, req, ok)


async def _get_countries(fake, req: Request, ok) -> Response:
    return ok(req, COUNTRIES)


async def _patch_me(fake, req: Request, ok) -> Response:
    from soak.fake_of import automations
    body = await _body(req)
    s = settings(fake)
    if isinstance(body, dict):
        s.update({k: v for k, v in body.items() if k in s})
        prof = _state(fake)["profile"]
        for k in PICTURES:
            v = body.get(k)
            if v == "":
                prof[k] = None
                prof["pending"].pop(k, None)
            elif isinstance(v, dict) and v.get("processId"):
                prof["pending"][k] = (picture_url(str(v["processId"])), _clock() + STALE_S)
        if isinstance(body.get("about"), str):
            prof["about"] = body["about"]
    return await automations._me(fake, req, ok)


async def _get_notifications(fake, req: Request, ok, transport: str) -> Response:
    # OF groups only with ?group=1; bare, it answers the flat item list (measured live)
    groups = notifications(fake, transport)
    if groups is None:
        fake._log(req, 404, False)
        return JSONResponse({"error": {"code": 0, "message": "Not found (soak fake: unmodelled)"}}, status_code=404)
    return ok(req, groups if req.query_params.get("group") == "1" else list(_items(groups)))


async def _patch_notifications(fake, req: Request, ok) -> Response:
    body = await _body(req)
    out: dict[str, Any] = {}
    for transport, items in ((body or {}).get("notifications") or {}).items():
        groups = notifications(fake, transport) or []
        for it in items or []:
            for x in _items(groups):
                if x.get("code") == it.get("code") and "value" in it:
                    v = it["value"]
                    x["isEnabled"] = bool(v)
                    x["value"] = v if type(v) in (int, float) else int(bool(v))
        out[transport] = groups
    fake._log(req, 200, True, body)
    return JSONResponse(out)


ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/users/me/settings"), _get_settings),
    ("PATCH", re.compile(r"/api2/v2/users/me/settings/security"), _patch_security),
    ("PATCH", re.compile(r"/api2/v2/users/me"), _patch_me),
    ("GET", re.compile(r"/api2/v2/users/settings/notifications/([a-z]+)"), _get_notifications),
    ("PATCH", re.compile(r"/api2/v2/users/settings/notifications"), _patch_notifications),
    ("PUT", re.compile(r"/api2/v2/users/me/settings/security"), _put_security),
    ("GET", re.compile(r"/api2/v2/countries"), _get_countries),
]
