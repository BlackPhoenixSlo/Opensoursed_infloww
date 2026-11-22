"""Uploads, scheduled posts and Remove from vault in the fake OnlyFans (Phase 6 ticket 97: the upload and duplicate-id
proofs; ofm-not-yet ticket 131: the Record video and Record voice proofs), one state for every read and write.

Mounted from app.py, the upload chain as service/of_upload.py `upload_media` walks it:
  GET    /vault/media/hash?h=&size=   the dedupe: an S3 ETag a post already filed answers 200 `{id, hidden}`, any
                                      other 404 (of_upload `vault_media_lookup_hash`)
  POST   /upload/signed/create        `{key, parts: 1, ...}` -> `{putUrl, getUrl, key, uploadToken}`: the key with the
                                      Creator's id spliced in, the putUrl this fake's `/{the sent key}` (OF's S3 path
                                      shape, `upload/<uuid>/<n>/<file name>`, service/of_upload.py); 400 "Invalid file
                                      type" for audio/mp4 / .m4a (live 2026-11-21, ticket 53v)
  PUT    /upload/{path}               the S3 stand-in (outside /api2/v2, unsigned): stores the bytes' md5 and answers
                                      it as the `ETag` header (a single-part S3 ETag)
  POST   /file/upload                 convert's stand-in (convert.onlyfans.com, sent here by the harness's Relay):
                                      a claim naming a stored key, its token and its ETag -> `{processId, host,
                                      sourceUrl, extra, files, thumbs}`; any other 400 "Invalid input."
  POST   /posts                       a post: each `mediaFiles` entry a listed vault id or a claim's `{processId,
                                      ...}`, which files a new vault item under its ETag. Answers the stored post. One
                                      with `isScheduled` + `scheduledDate` is scheduled (queue.py's GET /schedules),
                                      `isScheduled` alone saved for later (later/post); any other is stored and never
                                      listed (nothing more of it is modelled).
  GET    /schedules/later/post        the posts saved for later (`isScheduled`, no `scheduledDate`), newest first,
                                      `{list, hasMore, syncInProcess}`, `offset`/`limit` honoured (service/of_reads.py
                                      `schedules_later_post`): each a queue row wrapping the post in `entity`,
                                      `publishDateTime` null, the row's own `id` its schedule item's, not the post's
                                      (the capture queue-saved-post-item.json's shape); a dated post is NOT here (OF,
                                      ticket 136)
  GET    /posts/{id}                  the post, with its `media`
  GET    /labels                      the Creator's post labels: the captured new-post-labels.json (ticket 35)
  GET    /posts/tagged-friend-users   the creators a post may Co-tag (ofm-not-yet ticket 98): new-post-tags.json's
                                      items, `name` a case-blind search of name and username, `offset`/`limit`
                                      honoured, `{items, hasMore}` (service/of_reads.py `tagged_friend_users`)
  DELETE /posts/{id}                  the post deleted; its vault items stay
  PUT    /vault/media/hidden          `{mediaIds}`: OF's Remove from vault, one-way (of_sends `hide_vault_media`); a
                                      hidden item leaves the vault listing and its ETag still answers the dedupe,
                                      `hidden: true` (of_upload's own note on a hidden hit)
  GET    /users/{id}/posts            the Creator's published posts, newest first (of_reads `user_posts`, shaped from
                                      profile-posts.json); any other user's 404 (ticket 99)
Publish now (ticket 99): queue.py's `PUT /schedules/{id}/publish` naming a live scheduled post's schedule item
publishes it (`publish`): it leaves GET /schedules and shows on the profile.
Co-tags (ofm-not-yet ticket 98): a post body's `rfTag` (the Relay's `_write_tag_block` sends it with `userTags` beside
it) is kept, and the post's reads (GET /posts/{id}, its /schedules row, its profile row) answer it as `rfTag`, the
tagged creators' ids. An immediate post (no `isScheduled`) is published at once: it shows on the profile.
ASSUMPTION (ticket 98): OnlyFans's post read names its Co-tags `rfTag`, as ids (rung 5: no tagged post's read is
captured; the body's own key); overturned by the first live read of a tagged post, which then names the field. Tags
are stored as sent, never checked against the taggable list (whether OnlyFans validates them at create or at publish
is the Co-tag proofs' open unknown).
Read beside vault.py's listing (filed, visible items, newest first, ahead of the seeded ones) and queue.py's
GET /schedules (each live scheduled post as a `post` schedule item, shaped from queue-schedules-2026-11.json; the
filters as `schedule_rows` reads them).
ASSUMPTION: an `isScheduled` post without `scheduledDate` is a saved-for-later one (rung 5: no capture of OF's
save-for-later post body); overturned by that capture, which then names the body.
Measured for /schedules (queue--scheduled-post-endpoint.json): the date range is honoured, offset is ignored, limit=1
and limit=100 both returned every row in range, the answer is {list, syncInProcess} with no hasMore. NOT measured, so
each is an ASSUMPTION (rung 5: the simplest reading of the capture), with the live read that would overturn it:
- both ends of the range are inclusive; overturned by a read with publishDate = publishDateEnd = a post's own day that
  comes back empty (or a post on publishDateEnd's day missing).
- a row's day is its `publishDateTime` in `filter[timeZone]`; overturned by a read naming a far-off zone (e.g.
  Pacific/Kiritimati) for a post near midnight UTC whose day does not shift.
- `limit` is fully ignored, not applied per day (the capture had one post per day, so the two were not separated);
  overturned by limit=1 over a range with two posts on the same day that returns one.
- a missing `filter[publishDate]`/`filter[publishDateEnd]` leaves that end open, and rows come by `publishDateTime`,
  earliest first (the Queue page always sends all three filters); overturned by a read without them, or out of order.
- a malformed date or an unknown time zone answers 400 (OF's error envelope), so a reader bug such as a literal `{tz}`
  fails in fake mode too; overturned by a live read where OF accepts one.

Shapes: the post from queue-edit-post.json (captured), ids, text and dates replaced. ASSUMPTION: the dedupe hit,
signed/create, convert, post `media`, delete and hide answers are as the repo's code reads them (of_upload,
of_sends; none is a captured answer); overturned by their Request captures (ticket 12). ASSUMPTION: a claim becomes a
vault item only once a post references it (the repo's vault import, VERIFIED LIVE there); a post holding one id twice
is stored as sent (what OnlyFans does with it is what the duplicate-id proof records).
ASSUMPTION (ticket 99): a post may hold a hidden vault id (the re-upload's dedupe hit answers it, of_upload sends it),
and a published post shows its hidden media on the profile; what OnlyFans does is what the Publish now proof records
(planted refusal: scripts/of-live-proof/fake_layer.py `hidden-refused`).
"""
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

_PUTS, _CONVERTED = "_soak_storage_puts", "_soak_converted"   # ticket 67: storage path -> bytes; processId -> bytes
_CLAIMS = "_soak_claim_count"


@dataclass
class Post:
    n: int
    text: str
    media: list[int]
    scheduled_at: datetime | None   # None: not scheduled (stored, never listed) or `saved`
    created_at: datetime
    saved: bool = False   # ticket 136: `isScheduled` with no date, saved for later (later/post)
    deleted: bool = False
    published_at: datetime | None = None   # ticket 99: Publish now; then off the schedules, on the profile
    extras: dict[str, Any] = field(default_factory=dict)   # ticket 35: the body's labels, expiry, target (`_extras`)

    @property
    def id(self) -> int:
        return ids.post_id(self.n)

    @property
    def schedule(self) -> int:
        return ids.post_schedule_id(self.n)


def hidden(fake) -> set[str]:
    """The vault media ids removed from the vault (`PUT /vault/media/hidden`), as strings."""
    return {str(i) for i in state(fake)["hidden"]}


def state(fake) -> dict[str, Any]:
    """posts {id: Post}, puts {token: {key, etag}}, claims {processId: etag}, etags {etag: vault id}, uploads [vault
    id] (filing order) and hidden {vault id}, kept on the FakeOF object (as queue.py's items)."""
    return fake.__dict__.setdefault("_soak_posts", {"posts": {}, "puts": {}, "claims": {}, "etags": {},
                                                    "uploads": [], "hidden": set()})


def converted(fake) -> dict[str, bytes]:
    """Ticket 67: the bytes each convert claim's processId names (its storage PUT's), for the fake's /cdn."""
    return fake.__dict__.setdefault(_CONVERTED, {})


def _next(fake, counter: str) -> int:
    fake.__dict__[counter] = fake.__dict__.get(counter, 0) + 1
    return fake.__dict__[counter]


def _seeded() -> set[int]:
    return {ids.vault_media_id(n) for n in range(1, MEDIA_COUNT + 1)}


def listed(fake, seeded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """vault.py's listing: the filed, visible uploads (newest first), then the seeded items not hidden."""
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
    """The post as GET /posts/{id} answers it (queue-edit-post.json), with its `media`."""
    d = render._tpl("queue-edit-post.json")
    d.pop("_source", None)
    d.pop("author", None)   # the Creator's own profile: not modelled here
    at = p.scheduled_at or p.created_at
    d.update(id=p.id, postedAt=iso(at), postedAtPrecise=f"{at.timestamp():.6f}", text=p.text, rawText=p.text,
             media=[{"id": vid, "type": "photo", "isReady": True, "canView": True} for vid in p.media])
    d.update(_extras(p.extras, iso(at)))
    return d


def schedule_filter(q) -> Any:
    """queue.py's GET /schedules filters -> `within(datetime) -> bool`: its day in `filter[timeZone]` (default UTC) in
    `filter[publishDate]`..`filter[publishDateEnd]`, both inclusive, a missing end open (module docstring). Raises
    ValueError on a malformed date or an unknown time zone (the route answers 400)."""
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
    """queue.py's GET /schedules: each live scheduled post as a `post` schedule item, its time `within` the filters."""
    tpl = next(x for x in render.fixture("queue-schedules-2026-11.json")["list"] if x["type"] == "post")
    rows = []
    for p in _scheduled(fake):
        if not within(p.scheduled_at):
            continue
        d = json.loads(json.dumps(tpl))
        d["entity"].update(id=p.id, postedAt=iso(p.scheduled_at), postedAtPrecise=f"{p.scheduled_at.timestamp():.6f}",
                           text=p.text, rawText=p.text, mediaCount=len(p.media),
                           media=[{"id": vid, "type": "photo", "canView": True} for vid in p.media])
        d["entity"].update(_extras(p.extras, iso(p.scheduled_at)))   # ticket 35's read-back (now off /schedules)
        d.update(id=p.schedule, publishDateTime=iso(p.scheduled_at), createdDateTime=iso(p.created_at))
        rows.append(d)
    return rows


def _scheduled(fake) -> list[Post]:
    """The live scheduled posts, in creation order."""
    return [p for p in state(fake)["posts"].values()
            if not p.deleted and p.scheduled_at is not None and p.published_at is None]


def publish(fake, sid: int) -> bool:
    """Ticket 99: Publish now on the live scheduled post whose schedule item is `sid`; False when there is none."""
    p = next((x for x in _scheduled(fake) if x.schedule == sid), None)
    if p is None:
        return False
    p.published_at = now_utc()
    return True


async def _profile(fake, req: Request, ok, uid: str) -> Response:
    """GET /users/{id}/posts (ticket 99): the Creator's published posts, newest first, in profile-posts.json's item
    shape (its `author` dropped, as `entity`); `limit` honoured. Another user's: 404."""
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
        d.update(_tags(p.extras))   # ticket 98
        rows.append(d)
    return ok(req, rows[:int(req.query_params.get("limit") or 10)])


async def _later(fake, req: Request, ok) -> Response:
    """GET /schedules/later/post (tickets 131, 136): the posts saved for later (no date), newest first, paged, in the
    captured row shape (`publishDateTime` null)."""
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


# ── the upload chain ──

async def _hash(fake, req: Request, ok) -> Response:
    st = state(fake)
    vid = st["etags"].get(req.query_params.get("h") or "")
    if vid is None:
        return _error(req, ok, 404, "Not found")
    return ok(req, {"id": vid, "hidden": vid in st["hidden"]})


# ofm-not-yet ticket 53v: OF's signed/create refused a voice note sent as `contentType: "audio/mp4"`, key
# `.../voice-<n>.m4a`, with 400 {"error":{"code":0,"message":"Invalid file type"}} (live 2026-11-21, p2.record-voice);
# `video/mp4` .mp4 passed on the same run. ASSUMPTION: OF refuses only this type here; its full allowlist is unknown
# (rung 4: refusing more could fail a type OF takes; OF's own voice recorder sends audio/mpeg, audio/ogg or audio/wav,
# app/lib/ofMirrorComposer.ts VOICE_TYPES, all accepted); overturned by a live refusal of another type, added here.
_REFUSED_TYPES, _REFUSED_EXTS = frozenset({"audio/mp4"}), (".m4a",)


async def _signed(fake, req: Request, ok) -> Response:
    """One presigned PUT on this fake under the caller's key, the Creator's id spliced in after `upload/` (live
    2026-11-21, ofm-not-yet ticket 53). A refused type (_REFUSED_TYPES / _REFUSED_EXTS) answers OF's 400 "Invalid file
    type"."""
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
    # the newest signed/create naming this path (of_upload's keys are unique; a reused one is its last token's)
    put = next((x for x in reversed(state(fake)["puts"].values()) if x["path"] == req.scope["path"]), None)
    if put is None:
        fake._log(req, 404, True)
        return Response(status_code=404)
    data = await req.body()
    fake.__dict__.setdefault(_PUTS, {})[req.url.path] = data   # ticket 67: the claim's bytes
    put["etag"] = hashlib.md5(data).hexdigest()
    fake._log(req, 200, True)
    return Response(status_code=200, headers={"ETag": f'"{put["etag"]}"'})


def png_intact(data: bytes) -> bool:
    """False only for a PNG with a chunk whose CRC fails or that runs past the end; any other bytes pass."""
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
    if data is not None and not png_intact(data):   # OF's own reply to a PNG whose chunk CRCs fail (live 2026-11-21)
        fake._log(req, 400, False)
        return JSONResponse({"error": {"code": 0, "message": "Image is corrupted"}}, status_code=400)
    pid = f"soak-process-{_next(fake, _CLAIMS)}"
    st["claims"][pid] = etag
    if data is not None:
        converted(fake)[pid] = data
    fake._log(req, 200, True)
    return JSONResponse({"processId": pid, "host": "convert.soak", "sourceUrl": f"{fake.origin}{put['path']}",
                         "extra": "soak", "files": [], "thumbs": []})


# ── posts and Remove from vault ──

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
    known = _seeded() | set(st["uploads"])   # ticket 99: a hidden id too (ASSUMPTION above)
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
    if not body.get("isScheduled"):   # ticket 98: an immediate post is published at once
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
    ("GET", re.compile(r"/api2/v2/schedules/later/post"), _later),   # ticket 131
    ("GET", re.compile(r"/api2/v2/vault/media/hash"), _hash),
    ("POST", re.compile(r"/api2/v2/upload/signed/create"), _signed),
    ("POST", re.compile(r"/api2/v2/posts"), _create),
    ("GET", re.compile(r"/api2/v2/posts/(\d+)"), _get),
    ("DELETE", re.compile(r"/api2/v2/posts/(\d+)"), _delete),
    ("PUT", re.compile(r"/api2/v2/vault/media/hidden"), _hide),
    ("GET", re.compile(r"/api2/v2/users/(\d+)/posts"), _profile),   # ticket 99
]


# ofm-not-yet ticket 35: New post's labels, expiration and target on the post (`entity`), from OF's body
# (service/of_sends.py `_post_body`: `labelIds`, `expireDays`, `fundRaisingTargetAmount` + `fundRaisingTipsPresets`),
# named as OF's JS names them (docs/plans/of-manager-api-catalogue.md, Posts): `labelStates` items `{id, isAdded}`,
# `expiredAt` = `postedAt` + the days, `fundRaising{target,presets}`. A field the body did not send is absent (the
# captured entity has none of the three). Plus the labels dialog's read.
def _extras(body: dict, posted_at: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if body.get("labelIds"):
        out["labelStates"] = [{"id": int(i), "isAdded": True} for i in body["labelIds"]]
    if body.get("expireDays"):
        out["expiredAt"] = (datetime.fromisoformat(posted_at) + timedelta(days=int(body["expireDays"]))).isoformat()
    if body.get("fundRaisingTargetAmount"):
        out["fundRaising"] = {"target": body["fundRaisingTargetAmount"],
                              "presets": list(body.get("fundRaisingTipsPresets") or [])}
    out.update(_tags(body))   # ticket 98
    return out


async def _labels(fake, req: Request, ok) -> Response:
    data = render.fixture("new-post-labels.json")
    data.pop("_source", None)
    return ok(req, data)


ROUTES.append(("GET", re.compile(r"/api2/v2/labels"), _labels))


# ofm-not-yet ticket 98: Co-tags on a post (module docstring) and the taggable-creators read.
def _tags(body: dict) -> dict[str, Any]:
    """The post's Co-tags as its reads answer them: `rfTag`, the ids the body sent (none: absent)."""
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
