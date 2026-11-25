from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_STATE = "_soak_profile_lists"
SOCIAL_KEYS = ("socialMedia", "label", "link", "username")
SOCIAL_PROVIDERS = [
    {"socialMedia": "instagram", "label": "Instagram", "isLink": False, "isShowAt": False},
    {"socialMedia": "x", "label": "X", "isLink": False, "isShowAt": False},
    {"socialMedia": "facebook", "label": "Facebook", "isLink": False, "isShowAt": False},
    {"socialMedia": "youtube", "label": "Youtube", "isLink": False, "isShowAt": True},
    {"socialMedia": "tiktok", "label": "Tiktok", "isLink": False, "isShowAt": True},
    {"socialMedia": "snapchat", "label": "Snapchat", "isLink": False, "isShowAt": False},
    {"socialMedia": "amazon", "label": "Amazon", "isLink": True, "isShowAt": False},
    {"socialMedia": "twitch", "label": "Twitch", "isLink": False, "isShowAt": False},
    {"socialMedia": "patreon", "label": "Patreon", "isLink": False, "isShowAt": False},
    {"socialMedia": "pinterest", "label": "Pinterest", "isLink": False, "isShowAt": False},
    {"socialMedia": "etsy", "label": "Etsy", "isLink": True, "isShowAt": False},
    {"socialMedia": "bereal", "label": "Bereal", "isLink": True, "isShowAt": False},
    {"socialMedia": "kick", "label": "Kick", "isLink": False, "isShowAt": False},
    {"socialMedia": "depop", "label": "Depop", "isLink": False, "isShowAt": False},
    {"socialMedia": "poshmark", "label": "Poshmark", "isLink": False, "isShowAt": False},
    {"socialMedia": "vsco", "label": "Vsco", "isLink": True, "isShowAt": False},
    {"socialMedia": "threads", "label": "Threads", "isLink": False, "isShowAt": True},
    {"socialMedia": "throne", "label": "Throne", "isLink": False, "isShowAt": False},
    {"socialMedia": "shopltk", "label": "Shopltk", "isLink": False, "isShowAt": False},
    {"socialMedia": "oftv", "label": "OFTV", "isLink": False, "isShowAt": False},
    {"socialMedia": "bsky", "label": "Bluesky", "isLink": False, "isShowAt": False},
    {"socialMedia": "spoilme", "label": "SpoilMe", "isLink": False, "isShowAt": False},
]
SOCIAL_MAX = 10
# ASSUMPTION: OF gives this whole body for any socialMedia outside its providers; the per-provider username rule is not captured.
INVALID_SOCIAL = {"error": {"code": 0, "message": "SocialMedia contains invalid value"},
                  "errors": {"socialMedia": ["SocialMedia contains invalid value"], "username": ["Username not allowed."]}}


def social_item(body: dict) -> dict[str, Any]:
    return {k: str(body.get(k) or "") for k in SOCIAL_KEYS}


def link_item(body: dict) -> dict[str, Any]:
    return {"sort": 0, "url": str(body.get("link") or ""), "title": "", "description": "",
            "image": {"src": "", "thumbs": {"c50": "", "c144": ""}, "width": 0, "height": 0}}


def rows(fake, kind: str) -> list[dict[str, Any]]:
    st = fake.__dict__.setdefault(_STATE, {})
    return st.setdefault(kind, [])


def _social_refusal(body: dict) -> JSONResponse | None:
    if body.get("socialMedia") in {p["socialMedia"] for p in SOCIAL_PROVIDERS}:
        return None
    return JSONResponse(INVALID_SOCIAL, status_code=400)


async def _init(fake, req: Request, ok) -> Response:
    return ok(req, {"socialMediaProviders": SOCIAL_PROVIDERS, "socialButtonsMaxLimit": SOCIAL_MAX})


def _surface(kind: str, item, first_id: int, refuse=lambda body: None):
    async def _list(fake, req: Request, ok) -> Response:
        return ok(req, rows(fake, kind))

    async def _add(fake, req: Request, ok) -> Response:
        raw = await req.body()
        body = json.loads(raw) if raw else {}
        refused = refuse(body)
        if refused is not None:
            fake._log(req, refused.status_code, True, body)
            return refused
        items = rows(fake, kind)
        new_id = max((int(r["id"]) for r in items), default=first_id) + 1
        items.append({"id": new_id, **item(body)})
        fake._log(req, 200, True, body)
        return JSONResponse(items)

    async def _delete(fake, req: Request, ok, rid: str) -> Response:
        items = rows(fake, kind)
        hit = next((r for r in items if str(r["id"]) == rid), None)
        if hit is None:
            fake._log(req, 404, True)
            return JSONResponse({"error": {"code": 0, "message": "Not found"}}, status_code=404)
        items.remove(hit)
        fake._log(req, 200, True)
        return JSONResponse({"success": True})

    return _list, _add, _delete


_social = _surface("social", social_item, 6900, _social_refusal)
_links = _surface("links", link_item, 7000)

ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/init"), _init),
    ("GET", re.compile(r"/api2/v2/users/social/buttons"), _social[0]),
    ("PUT", re.compile(r"/api2/v2/users/social/buttons"), _social[1]),
    ("DELETE", re.compile(r"/api2/v2/users/social/buttons/(\d+)"), _social[2]),
    ("GET", re.compile(r"/api2/v2/users/links"), _links[0]),
    ("PUT", re.compile(r"/api2/v2/users/links"), _links[1]),
    ("DELETE", re.compile(r"/api2/v2/users/links/(\d+)"), _links[2]),
]
