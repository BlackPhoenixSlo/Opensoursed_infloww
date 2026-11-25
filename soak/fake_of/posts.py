from __future__ import annotations

import hashlib
import json
import re
import secrets
import struct
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from soak import ids
from soak.fake_of import render
from soak.fake_of.vault import MEDIA_COUNT, media
from soak.world import iso, now_utc

_PUTS, _CONVERTED = "_soak_storage_puts", "_soak_converted"
_CLAIMS = "_soak_claim_count"


@dataclass
class Post:
    n: int
    text: str
    media: list[int]
    scheduled_at: datetime | None
    created_at: datetime
    saved: bool = False
    deleted: bool = False
    published_at: datetime | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> int:
        return ids.post_id(self.n)

    @property
    def schedule(self) -> int:
        return ids.post_schedule_id(self.n)


def hidden(fake) -> set[str]:
    return {str(i) for i in state(fake)["hidden"]}


def state(fake) -> dict[str, Any]:
    """posts {id: Post}, puts {token: {key, etag}}, claims {processId: etag}, etags {etag: vault id}, uploads [vault
    id] (filing order) and hidden {vault id}, kept on the FakeOF object (as queue.py's items)."""
    return fake.__dict__.setdefault("_soak_posts", {"posts": {}, "puts": {}, "claims": {}, "etags": {},
                                                    "uploads": [], "hidden": set()})


def converted(fake) -> dict[str, bytes]:
    return fake.__dict__.setdefault(_CONVERTED, {})


def _next(fake, counter: str) -> int:
    fake.__dict__[counter] = fake.__dict__.get(counter, 0) + 1
    return fake.__dict__[counter]


def _seeded() -> set[int]:
    return {ids.vault_media_id(n) for n in range(1, MEDIA_COUNT + 1)}


def listed(fake, seeded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    st = state(fake)
    up = [media(ids.UPLOADED + k) for k, vid in enumerate(st["uploads"], 1) if vid not in st["hidden"]]
    return up[::-1] + [m for m in seeded if m["id"] not in st["hidden"]]


def _when(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def _error(req: Request, ok, status: int, message: str) -> Response:
    return ok(req, {"error": {"code": 0, "message": message}}, status)


async def _json(req: Request) -> Any:
    raw = await req.body()
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def entity(p: Post) -> dict[str, Any]:
    d = render._tpl("queue-edit-post.json")
    d.pop("_source", None)
    d.pop("author", None)
    at = p.scheduled_at or p.created_at
    d.update(id=p.id, postedAt=iso(at), postedAtPrecise=f"{at.timestamp():.6f}", text=p.text, rawText=p.text,
             media=[{"id": vid, "type": "photo", "isReady": True, "canView": True} for vid in p.media])
    d.update(_extras(p.extras, iso(at)))
    return d


def schedule_filter(q) -> Any:
    try:
        tz = ZoneInfo(q.get("filter[timeZone]") or "UTC")
    except Exception as e:  # noqa: BLE001  (ZoneInfoNotFoundError, or a key ZoneInfo cannot read at all)
        raise ValueError(f"unknown time zone: {e}") from e
    lo, hi = ((date.fromisoformat(q[k]) if q.get(k) else None) for k in ("filter[publishDate]", "filter[publishDateEnd]"))

    def within(at: datetime) -> bool:
        day = at.astimezone(tz).date()
        return (lo is None or day >= lo) and (hi is None or day <= hi)
    return within


def schedule_rows(fake, within) -> list[dict[str, Any]]:
    tpl = next(x for x in render.fixture("queue-schedules-2026-11.json")["list"] if x["type"] == "post")
    rows = []
    for p in _scheduled(fake):
        if not within(p.scheduled_at):
            continue
        d = json.loads(json.dumps(tpl))
        d["entity"].update(id=p.id, postedAt=iso(p.scheduled_at), postedAtPrecise=f"{p.scheduled_at.timestamp():.6f}",
                           text=p.text, rawText=p.text, mediaCount=len(p.media),
                           media=[{"id": vid, "type": "photo", "canView": True} for vid in p.media])
        d["entity"].update(_extras(p.extras, iso(p.scheduled_at)))
        d.update(id=p.schedule, publishDateTime=iso(p.scheduled_at), createdDateTime=iso(p.created_at))
        rows.append(d)
    return rows


def _scheduled(fake) -> list[Post]:
    return [p for p in state(fake)["posts"].values()
            if not p.deleted and p.scheduled_at is not None and p.published_at is None]


def publish(fake, sid: int) -> bool:
    p = next((x for x in _scheduled(fake) if x.schedule == sid), None)
    if p is None:
        return False
    p.published_at = now_utc()
    return True


async def _profile(fake, req: Request, ok, uid: str) -> Response:
    if int(uid) != int(fake.world.creator_id):
        return _error(req, ok, 404, "User not found")
    live = [p for p in state(fake)["posts"].values() if not p.deleted and p.published_at is not None]
    rows = []
    for p in sorted(live, key=lambda x: x.published_at, reverse=True):
        d = render._tpl("profile-posts.json", 0)
        d.pop("author", None)
        d.update(id=p.id, postedAt=iso(p.published_at), postedAtPrecise=f"{p.published_at.timestamp():.6f}",
                 text=p.text, rawText=p.text, mediaCount=len(p.media), isMediaReady=True,
                 media=[{"id": vid, "type": "photo", "isReady": True, "canView": True} for vid in p.media])
        d.update(_tags(p.extras))
        rows.append(d)
    return ok(req, rows[:int(req.query_params.get("limit") or 10)])


async def _later(fake, req: Request, ok) -> Response:
    q = req.query_params
    off, lim = int(q.get("offset") or 0), int(q.get("limit") or 10)
    rows = []
    for p in [x for x in state(fake)["posts"].values() if x.saved and not x.deleted][::-1]:
        post = render._tpl("queue-saved-post-item.json", "list", 0, "entity")
        post.update(id=p.id, postedAt=iso(p.created_at), rawText=p.text, text=f"<p>{p.text}</p>",
                    media=[{"id": vid, "type": "photo", "canView": True} for vid in p.media], mediaCount=len(p.media),
                    isScheduled=True, scheduledDate=None)
        post.update(_extras(p.extras, iso(p.created_at)))
        row = render._tpl("queue-saved-post-item.json", "list", 0)
        row.update(id=p.schedule, publishDateTime=None, createdDateTime=iso(p.created_at), entity=post)
        rows.append(row)
    page = rows[off:off + lim]
    return ok(req, {"list": page, "hasMore": off + len(page) < len(rows), "syncInProcess": False})



async def _hash(fake, req: Request, ok) -> Response:
    st = state(fake)
    vid = st["etags"].get(req.query_params.get("h") or "")
    if vid is None:
        return _error(req, ok, 404, "Not found")
    return ok(req, {"id": vid, "hidden": vid in st["hidden"]})


# OF's signed/create refused a voice note as audio/mp4 .m4a with 400 "Invalid file type" (live); video/mp4 passed. Its full allowlist is unknown, so only this is refused.
_REFUSED_TYPES, _REFUSED_EXTS = frozenset({"audio/mp4"}), (".m4a",)


async def _signed(fake, req: Request, ok) -> Response:
    body = await _json(req)
    if not isinstance(body, dict) or not str(body.get("key") or "").startswith("upload/") or body.get("parts") != 1:
        return _error(req, ok, 400, "soak fake: one-part signed upload only")
    ctype = str(body.get("contentType") or "").split(";")[0].strip().lower()
    if ctype in _REFUSED_TYPES or str(body.get("key") or "").lower().endswith(_REFUSED_EXTS):
        return _error(req, ok, 400, "Invalid file type")
    token = secrets.token_hex(8)
    key = f"upload/{fake.world.creator_id}/{body['key'][len('upload/'):]}"
    state(fake)["puts"][token] = {"key": key, "path": f"/{key}", "etag": None}
    return ok(req, {"putUrl": f"{fake.origin}/{quote(key)}?X-Amz-Signature=soak",
                    "getUrl": f"{fake.origin}/{quote(key)}", "key": key, "uploadToken": token})


async def storage_put(fake, req: Request) -> Response:
    put = next((x for x in reversed(state(fake)["puts"].values()) if x["path"] == req.scope["path"]), None)
    if put is None:
        fake._log(req, 404, True)
        return Response(status_code=404)
    data = await req.body()
    fake.__dict__.setdefault(_PUTS, {})[req.url.path] = data
    put["etag"] = hashlib.md5(data).hexdigest()
    fake._log(req, 200, True)
    return Response(status_code=200, headers={"ETag": f'"{put["etag"]}"'})


def png_intact(data: bytes) -> bool:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    i = 8
    while i < len(data):
        if i + 12 > len(data):
            return False
        n = struct.unpack(">I", data[i:i + 4])[0]
        end = i + 8 + n
        if end + 4 > len(data) or struct.unpack(">I", data[end:end + 4])[0] != zlib.crc32(data[i + 4:end]) & 0xFFFFFFFF:
            return False
        i = end + 4
    return True


async def convert(fake, req: Request) -> Response:
    """The convert claim: a new processId holding the bytes its upload PUT (ticket 67: a profile picture saved with
    this item reads back as exactly those bytes). The claim must name its signed/create's key, uploadToken and the
    PUT's ETag (ticket 97); a corrupt PNG is refused before anything is claimed."""
    form = await req.form()
    st = state(fake)
    put = st["puts"].get(str(form.get("file[uploadToken]") or ""))
    etag = str(form.get("file[ETag]") or "").strip('"')
    if put is None or put["etag"] is None or form.get("file[Key]") != put["key"] or etag != put["etag"]:
        fake._log(req, 400, True)
        return JSONResponse({"error": "Invalid input."}, status_code=400)
    data = fake.__dict__.get(_PUTS, {}).get(put["path"])
    # OF's own reply to a PNG whose chunk CRCs fail.
    if data is not None and not png_intact(data):
        fake._log(req, 400, False)
        return JSONResponse({"error": {"code": 0, "message": "Image is corrupted"}}, status_code=400)
    pid = f"soak-process-{_next(fake, _CLAIMS)}"
    st["claims"][pid] = etag
    if data is not None:
        converted(fake)[pid] = data
    fake._log(req, 200, True)
    return JSONResponse({"processId": pid, "host": "convert.soak", "sourceUrl": f"{fake.origin}{put['path']}",
                         "extra": "soak", "files": [], "thumbs": []})



def _file(st: dict[str, Any], etag: str) -> int:
    if etag not in st["etags"]:
        st["uploads"].append(ids.vault_media_id(ids.UPLOADED + len(st["uploads"]) + 1))
        st["etags"][etag] = st["uploads"][-1]
    return st["etags"][etag]


async def _create(fake, req: Request, ok) -> Response:
    body = await _json(req)
    st = state(fake)
    if not isinstance(body, dict):
        return _error(req, ok, 400, "soak fake: a post body is a JSON object")
    when = _when(body.get("scheduledDate")) if body.get("isScheduled") else None
    known = _seeded() | set(st["uploads"])
    out = []
    for m in body.get("mediaFiles") or []:
        if isinstance(m, int) and m in known:
            out.append(m)
        elif isinstance(m, dict) and m.get("processId") in st["claims"]:
            out.append(_file(st, st["claims"][m["processId"]]))
        else:
            return _error(req, ok, 400, f"Media not found: {m!r}")
    p = Post(n=len(st["posts"]) + 1, text=str(body.get("text") or ""), media=out, scheduled_at=when,
             created_at=now_utc(), saved=bool(body.get("isScheduled")) and not body.get("scheduledDate"), extras=body)
    if not body.get("isScheduled"):
        p.published_at = p.created_at
    st["posts"][p.id] = p
    return ok(req, entity(p))


def _live(fake, pid: str) -> Post | None:
    p = state(fake)["posts"].get(int(pid))
    return None if p is None or p.deleted else p


async def _get(fake, req: Request, ok, pid: str) -> Response:
    p = _live(fake, pid)
    return ok(req, entity(p)) if p else _error(req, ok, 404, "Post not found")


async def _delete(fake, req: Request, ok, pid: str) -> Response:
    p = _live(fake, pid)
    if p is None:
        return _error(req, ok, 404, "Post not found")
    p.deleted = True
    return ok(req, {"success": True})


async def _hide(fake, req: Request, ok) -> Response:
    body = await _json(req)
    st = state(fake)
    got = body.get("mediaIds") if isinstance(body, dict) else None
    if not isinstance(got, list) or not got or not all(isinstance(i, int) and i in _seeded() | set(st["uploads"])
                                                       for i in got):
        return _error(req, ok, 400, "Media not found")
    st["hidden"] |= set(got)
    return ok(req, {"success": True})


ROUTES = [
    ("GET", re.compile(r"/api2/v2/schedules/later/post"), _later),
    ("GET", re.compile(r"/api2/v2/vault/media/hash"), _hash),
    ("POST", re.compile(r"/api2/v2/upload/signed/create"), _signed),
    ("POST", re.compile(r"/api2/v2/posts"), _create),
    ("GET", re.compile(r"/api2/v2/posts/(\d+)"), _get),
    ("DELETE", re.compile(r"/api2/v2/posts/(\d+)"), _delete),
    ("PUT", re.compile(r"/api2/v2/vault/media/hidden"), _hide),
    ("GET", re.compile(r"/api2/v2/users/(\d+)/posts"), _profile),
]


def _extras(body: dict, posted_at: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if body.get("labelIds"):
        out["labelStates"] = [{"id": int(i), "isAdded": True} for i in body["labelIds"]]
    if body.get("expireDays"):
        out["expiredAt"] = (datetime.fromisoformat(posted_at) + timedelta(days=int(body["expireDays"]))).isoformat()
    if body.get("fundRaisingTargetAmount"):
        out["fundRaising"] = {"target": body["fundRaisingTargetAmount"],
                              "presets": list(body.get("fundRaisingTipsPresets") or [])}
    out.update(_tags(body))
    return out


async def _labels(fake, req: Request, ok) -> Response:
    data = render.fixture("new-post-labels.json")
    data.pop("_source", None)
    return ok(req, data)


ROUTES.append(("GET", re.compile(r"/api2/v2/labels"), _labels))


def _tags(body: dict) -> dict[str, Any]:
    tags = body.get("rfTag") if isinstance(body, dict) else None
    return {"rfTag": [int(i) for i in tags if str(i).isdigit()]} if isinstance(tags, list) and tags else {}


async def _tagged(fake, req: Request, ok) -> Response:
    q = req.query_params
    name = (q.get("name") or "").strip().lower()
    items = [i for i in render.fixture("new-post-tags.json")["items"]
             if not name or name in str(i.get("name") or "").lower()
             or name in str((i.get("user") or {}).get("username") or "").lower()]
    off, lim = int(q.get("offset") or 0), int(q.get("limit") or 20)
    page = items[off:off + lim]
    return ok(req, {"items": page, "hasMore": off + len(page) < len(items)})


ROUTES.insert(0, ("GET", re.compile(r"/api2/v2/posts/tagged-friend-users"), _tagged))
