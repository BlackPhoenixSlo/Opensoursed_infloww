from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from soak import ids
from soak.fake_of import render
from soak.fake_of.vault import CDN_HOST
from soak.world import iso, now_utc

TIP_ROWS = 3
STRIP = ((1, 2, False), (2, 1, False), (3, 1, True))
HIGHLIGHTS = ((1, "Soak highlight 1", 2), (2, "Soak highlight 2", 1))
PAYOUTS = (("approved", 85.23, None), ("new", 40, None), ("rejected", 12.5, "Soak reason: payout method not verified"))
REFERRALS = (("approved", 7.25, None),)


def _ago(hours: int) -> str:
    return iso(now_utc().replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours))


def _photo(key: str) -> dict[str, Any]:
    base = f"https://{CDN_HOST}/files/soak/{key}"
    return {"id": None, "type": "photo", "canView": True, "convertedToVideo": False,
            "files": {"full": {"url": f"{base}/750x750.png?Policy=soak", "width": 750, "height": 750},
                      "thumb": {"url": f"{base}/300x300.png?Policy=soak", "width": 300, "height": 300},
                      "preview": {"url": f"{base}/750x750.png?Policy=soak", "width": 750, "height": 750}}}



def tip_rows(world) -> list[dict[str, Any]]:
    out = []
    for n, f in enumerate(world.fans[:TIP_ROWS], 1):
        out.append({
            "id": ids.notification_id(900 + n), "type": "tip", "createdAt": _ago(n), "isRead": n > 1,
            "text": "{NAME} sent you a tip of {AMOUNT}",
            "replacePairs": {"{NAME}": f.name, "{AMOUNT}": f"${n * 5}.00"},
            "user": {"view": "t", "id": f.id, "name": f.name, "username": f.username, "avatar": None},
        })
    return out


async def _notifications(fake, req: Request, ok) -> Response:
    if req.query_params.get("type") not in ("tip", "tipped"):
        from soak.fake_of import growth as _growth
        return await _growth._notifications(fake, req, ok)
    rows = tip_rows(fake.world)
    p = req.query_params
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 10)
    page = rows[off:off + lim]
    return ok(req, {"list": page, "hasMore": off + len(page) < len(rows)})



def _story(n: int, user_id: int, watched: bool, hours: int) -> dict[str, Any]:
    m = _photo(f"story/{n}")
    m["id"] = ids.story_id(n)
    return {"id": ids.story_id(n), "userId": user_id, "createdAt": _ago(hours), "isWatched": watched,
            "media": [m]}


def strip_users() -> list[dict[str, Any]]:
    out, n = [], 0
    for c, count, watched in STRIP:
        uid = ids.story_user_id(c)
        stories = []
        for _ in range(count):
            n += 1
            stories.append(_story(n, uid, watched, n))
        out.append({"id": uid, "name": f"Soak Story Creator {c}", "username": f"soakstory{c}", "avatar": None,
                    "isVerified": c == 1, "stories": stories})
    return out


async def _stories(fake, req: Request, ok) -> Response:
    return ok(req, strip_users())


async def _stories_map(fake, req: Request, ok) -> Response:
    out = []
    for u in strip_users():
        first = next((s for s in u["stories"] if not s["isWatched"]), u["stories"][0])
        out.append({"storyId": first["id"], "userId": u["id"],
                    "isWatched": all(s["isWatched"] for s in u["stories"])})
    return ok(req, out)


_MAP_KEY = re.compile(r"map\[(\d+)\]")


async def _stories_items(fake, req: Request, ok) -> Response:
    want = {int(m.group(1)) for k in req.query_params.keys() if (m := _MAP_KEY.fullmatch(k))}
    return ok(req, [s for u in strip_users() if u["id"] in want for s in u["stories"]])


async def _own_stories(fake, req: Request, ok, uid: str) -> Response:
    return ok(req, [])


async def _streams(fake, req: Request, ok) -> Response:
    return ok(req, {"list": []})



def highlights(world) -> list[dict[str, Any]]:
    out, n = [], 100
    for h, title, count in HIGHLIGHTS:
        stories = []
        for _ in range(count):
            n += 1
            stories.append(_story(n, world.creator_id, True, n))
        row = render._tpl("profile-highlights.json", "list", 0)
        row.update(id=ids.highlight_id(h), userId=world.creator_id, title=title, coverStoryId=stories[0]["id"],
                   cover=stories[0]["media"][0]["files"]["thumb"]["url"], storiesCount=count, createdAt=_ago(h),
                   stories=stories)
        out.append(row)
    return out


async def _highlights(fake, req: Request, ok, uid: str) -> Response:
    rows = [{k: v for k, v in h.items() if k != "stories"} for h in highlights(fake.world)]
    return ok(req, {"list": rows, "hasMore": False})


async def _highlight(fake, req: Request, ok, hid: str) -> Response:
    h = next((x for x in highlights(fake.world) if x["id"] == int(hid)), None)
    if h is None:
        return ok(req, {"error": {"code": 0, "message": "Not found"}}, 404)
    return ok(req, h)



def payout_rows(rows, first: int) -> list[dict[str, Any]]:
    tpl = render._tpl("statistics-payout-requests.json", "list", 0)
    return [{**tpl, "invoiceId": ids.invoice_id(first + i), "createdAt": _ago(24 * (i + 1)), "amount": amount,
             "currency": "USD", "state": state, "rejectReason": reason}
            for i, (state, amount, reason) in enumerate(rows)]


async def _payouts(fake, req: Request, ok) -> Response:
    return ok(req, {"list": payout_rows(PAYOUTS, 1), "marker": None})


async def _referrals(fake, req: Request, ok) -> Response:
    return ok(req, {"list": payout_rows(REFERRALS, 50), "marker": None})


ROUTES = [
    ("GET", re.compile(r"/api2/v2/users/notifications"), _notifications),
    ("GET", re.compile(r"/api2/v2/stories"), _stories),
    ("GET", re.compile(r"/api2/v2/stories/map"), _stories_map),
    ("GET", re.compile(r"/api2/v2/stories/items"), _stories_items),
    ("GET", re.compile(r"/api2/v2/users/(\d+)/stories"), _own_stories),
    ("GET", re.compile(r"/api2/v2/users/(\d+)/stories/highlights"), _highlights),
    ("GET", re.compile(r"/api2/v2/stories/highlights/(\d+)"), _highlight),
    ("GET", re.compile(r"/api2/v2/streams/feed"), _streams),
    ("GET", re.compile(r"/api2/v2/payouts/requests"), _payouts),
    ("GET", re.compile(r"/api2/v2/payouts/requests/referral"), _referrals),
]
