"""Profile list surfaces of the fake OnlyFans (Phase 3 tickets 69 and 70: Social media's buttons' and Things I Like's
links' fake-mode proofs), one state per list for every read and write.

Mounted from app.py beside the settings surface (after automations' gate rows, so its fault knobs still apply):
  GET    /users/social/buttons        the buttons, oldest first (a bare list: service/of_reads.py `social_buttons`)
  GET    /init                        only `{socialMediaProviders, socialButtonsMaxLimit}` (OF's lists, measured live
                                      2026-11-21: SOCIAL_PROVIDERS, 10): the Add button form's Button select
  PUT    /users/social/buttons        `{socialMedia, label, link, username}` appended (of_sends `add_social_button`);
                                      answers the full list (the capture record's response_shape); a `socialMedia`
                                      not in SOCIAL_PROVIDERS gets OF's 400 (INVALID_SOCIAL, measured live 2026-11-21)
  DELETE /users/social/buttons/{id}   removes that button only (of_sends `delete_social_button`); `{success: true}`
  GET    /users/links                 Things I Like's links, oldest first (of_reads `users_links`), each in OF's
                                      shape `{id, sort, url, title, description, image}` (measured live
                                      2026-11-21: the link is `url`, no `link` key)
  PUT    /users/links                 `{link}` appended as such an item (of_sends `add_users_link`); answers the
                                      full list
  DELETE /users/links/{id}            removes that link only (of_sends `delete_users_link`); `{success: true}`

The account starts with no buttons and no links, so the proof's undo puts the read back as it was. Every write is logged with its
body and applied before the response, so the next read reflects it. The replies follow the capture record's shapes;
the ids are the fake's own.
"""
from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_STATE = "_soak_profile_lists"
SOCIAL_KEYS = ("socialMedia", "label", "link", "username")
# OF's GET /init socialMediaProviders, measured live 2026-11-21 (22 items, OF's order) with socialButtonsMaxLimit 10.
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
# OF's answer to PUT /users/social/buttons with socialMedia "example" (measured live 2026-11-21). ASSUMPTION: OF gives
# this whole body (its username error included) for any socialMedia outside its providers; the username rule per
# provider is not captured, so the fake checks socialMedia alone.
INVALID_SOCIAL = {"error": {"code": 0, "message": "SocialMedia contains invalid value"},
                  "errors": {"socialMedia": ["SocialMedia contains invalid value"], "username": ["Username not allowed."]}}


def social_item(body: dict) -> dict[str, Any]:
    return {k: str(body.get(k) or "") for k in SOCIAL_KEYS}


def link_item(body: dict) -> dict[str, Any]:
    """OF's GET /users/links item for a PUT `{link}`: `url` the link; OF's scraped title/description/preview are the
    fake's blanks (it fetches no page)."""
    return {"sort": 0, "url": str(body.get("link") or ""), "title": "", "description": "",
            "image": {"src": "", "thumbs": {"c50": "", "c144": ""}, "width": 0, "height": 0}}


def rows(fake, kind: str) -> list[dict[str, Any]]:
    st = fake.__dict__.setdefault(_STATE, {})
    return st.setdefault(kind, [])


def _social_refusal(body: dict) -> JSONResponse | None:
    """OF's 400 for a socialMedia none of its providers has, else None."""
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
_links = _surface("links", link_item, 7000)  # ticket 70

ROUTES: list[tuple[str, re.Pattern, Any]] = [
    ("GET", re.compile(r"/api2/v2/init"), _init),
    ("GET", re.compile(r"/api2/v2/users/social/buttons"), _social[0]),
    ("PUT", re.compile(r"/api2/v2/users/social/buttons"), _social[1]),
    ("DELETE", re.compile(r"/api2/v2/users/social/buttons/(\d+)"), _social[2]),
    ("GET", re.compile(r"/api2/v2/users/links"), _links[0]),
    ("PUT", re.compile(r"/api2/v2/users/links"), _links[1]),
    ("DELETE", re.compile(r"/api2/v2/users/links/(\d+)"), _links[2]),
]
