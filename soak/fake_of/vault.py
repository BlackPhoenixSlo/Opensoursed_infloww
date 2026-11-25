from __future__ import annotations

import json
import re
import struct
import zlib
from datetime import timedelta
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from soak import ids
from soak.fake_of import render
from soak.fake_of.growth import _body, _not_found, _write
from soak.world import iso, now_utc

CDN_HOST = "fake-cdn.ofcdn.com"
MEDIA_COUNT = 24
_FOLDER = "Soak folder"
_STATE = "_soak_vault_folders"
_NEXT = "_soak_vault_folder_n"


def _png(side: int = 8) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80" * side for _ in range(side))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()


def thumb_url(n: int) -> str:
    return f"https://{CDN_HOST}/files/soak/{n}/300x300.png?Policy=soak"


def media(n: int) -> dict[str, Any]:
    d = render._tpl("vault-media-all.json", "list", 0)
    full = f"https://{CDN_HOST}/files/soak/{n}/750x750.png?Policy=soak"
    d["id"] = ids.vault_media_id(n)
    d["createdAt"] = iso(now_utc().replace(minute=0, second=0) - timedelta(hours=n))
    d["files"]["full"]["url"] = full
    d["files"]["preview"]["url"] = full
    d["files"]["thumb"]["url"] = thumb_url(n)
    d["files"]["squarePreview"]["url"] = f"https://{CDN_HOST}/files/soak/{n}/960x960.png?Policy=soak"
    return d


def _covers() -> list[dict[str, str]]:
    return [{"type": "photo", "url": thumb_url(n)} for n in range(1, min(3, MEDIA_COUNT) + 1)]


def _rows(d) -> list[dict[str, Any]]:
    rows = []
    for row in d["list"]:
        if row["type"] == "custom":
            continue
        row.update(videosCount=0, photosCount=0, gifsCount=0, audiosCount=0, medias=[], hasMedia=False)
        rows.append(row)
    tpl = next(i for i, r in enumerate(d["list"]) if r["type"] == "custom")
    for n in range(FOLDERS, 0, -1):
        folder = render._tpl("vault-lists.json", "list", tpl)
        media_n = MEDIA_COUNT if n == 1 else 0
        folder.update(id=ids.vault_list_id(n), name=f"{_FOLDER} {n}", hasMedia=bool(media_n), videosCount=0,
                      photosCount=media_n, gifsCount=0, audiosCount=0, medias=_covers() if media_n else [])
        rows.insert(3, folder)
    return rows



FOLDERS = 3
SORTS = ("name", "recent", "media", "custom", "default")
ORDERS = ("asc", "desc")


def order_state(fake) -> dict[str, Any]:
    st = getattr(fake, "_vault_order", None)
    if st is None:
        default = [r["id"] for r in _rows(render._tpl("vault-lists.json"))]
        last = ids.vault_list_id(FOLDERS)
        st = {"sort": "custom", "order": "desc", "custom": [last, *(i for i in default if i != last)]}
        fake._vault_order = st
    return st


def _sorted(rows: list[dict[str, Any]], st: dict[str, Any]) -> list[dict[str, Any]]:
    if st["sort"] == "custom":
        at = {i: k for k, i in enumerate(st["custom"])}
        return sorted(rows, key=lambda r: at.get(r["id"], len(at)))
    return rows[::-1] if st["order"] == "asc" else rows


async def _lists(fake, req: Request, ok) -> Response:
    d = render._tpl("vault-lists.json")
    st = order_state(fake)
    p = req.query_params
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 10)
    rows = _rows(d)
    rows[3 + FOLDERS:3 + FOLDERS] = [dict(f) for f in _created(fake)]
    rows = _sorted(rows, st)
    d["list"] = rows[off:off + lim]
    d["all"] = {"videosCount": 0, "photosCount": MEDIA_COUNT, "gifsCount": 0, "audiosCount": 0, "medias": _covers()}
    d["hasMore"] = off + len(d["list"]) < len(rows)
    d["sort"], d["order"] = st["sort"], st["order"]
    return ok(req, d)


async def _sort(fake, req: Request, ok) -> Response:
    raw = await req.body()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = raw.decode(errors="replace")
    st = order_state(fake)
    known = {r["id"] for r in _rows(render._tpl("vault-lists.json"))} | {f["id"] for f in _created(fake)}
    ok_body = False
    if isinstance(body, dict) and set(body) == {"customOrder", "sort"} and body["sort"] == "custom":
        got = body["customOrder"]
        if isinstance(got, list) and got and all(isinstance(i, int) and i in known for i in got) \
                and len(set(got)) == len(got):
            st.update(sort="custom", custom=list(got))
            ok_body = True
    elif isinstance(body, dict) and set(body) == {"sort", "order"} and body["sort"] in SORTS \
            and body["order"] in ORDERS:
        st.update(sort=body["sort"], order=body["order"])
        ok_body = True
    status = 200 if ok_body else 400
    fake._log(req, status, True, body)
    return JSONResponse({"success": True} if ok_body else {"error": {"code": 400, "message": "soak fake: bad sort body"}},
                        status_code=status)


async def _media(fake, req: Request, ok) -> Response:
    p = req.query_params
    off, lim = int(p.get("offset") or 0), int(p.get("limit") or 24)
    every = p.get("list") in (None, "", "all", str(ids.vault_list_id(1))) and p.get("type") in (None, "", "photo")
    items = [media(n) for n in range(1, MEDIA_COUNT + 1)] if every else []
    if every:
        from soak.fake_of import posts as _posts
        items = _posts.listed(fake, items)
    if p.get("sort") == "asc":
        items.reverse()
    page = items[off:off + lim]
    return ok(req, {"list": page, "hasMore": off + len(page) < len(items)})


def _created(fake) -> list[dict[str, Any]]:
    return fake.__dict__.setdefault(_STATE, [])


async def _one(fake, req: Request, ok, fid: str) -> Response:
    rows = [*_rows(render._tpl("vault-lists.json")), *_created(fake)]
    folder = next((f for f in rows if str(f["id"]) == fid), None)
    return ok(req, dict(folder)) if folder else ok(req, {"error": {"code": 0, "message": "Not found"}}, 404)


def _name(body: Any) -> str:
    return str((body if isinstance(body, dict) else {}).get("name") or "")


async def _create(fake, req: Request, ok) -> Response:
    body = await _body(req)
    fake.__dict__[_NEXT] = fake.__dict__.get(_NEXT, FOLDERS) + 1
    folder = {"id": ids.vault_list_id(fake.__dict__[_NEXT]), "type": "custom", "name": _name(body), "hasMedia": False,
              "canUpdate": True, "canDelete": True, "videosCount": 0, "photosCount": 0, "gifsCount": 0,
              "audiosCount": 0, "medias": []}
    _created(fake).append(folder)
    return _write(fake, req, dict(folder), body)


async def _rename(fake, req: Request, ok, fid: str) -> Response:
    body = await _body(req)
    folder = next((f for f in _created(fake) if str(f["id"]) == fid), None)
    if folder is None:
        return _not_found(fake, req, body)
    folder["name"] = _name(body)
    return _write(fake, req, dict(folder), body)


async def _delete(fake, req: Request, ok, fid: str) -> Response:
    body = await _body(req)
    rows = _created(fake)
    folder = next((f for f in rows if str(f["id"]) == fid), None)
    if folder is None:
        return _not_found(fake, req, body)
    rows.remove(folder)
    return _write(fake, req, {"success": True}, body)


async def cdn(fake, req: Request) -> Response:
    fake._log(req, 200, True)
    return Response(PNG, media_type="image/png")


ROUTES = [
    ("POST", re.compile(r"/api2/v2/vault/lists/sort"), _sort),
    ("GET", re.compile(r"/api2/v2/vault/lists"), _lists),
    ("GET", re.compile(r"/api2/v2/vault/lists/(\d+)"), _one),
    ("GET", re.compile(r"/api2/v2/vault/media"), _media),
    ("POST", re.compile(r"/api2/v2/vault/lists"), _create),
    ("PATCH", re.compile(r"/api2/v2/vault/lists/(\d+)"), _rename),
    ("DELETE", re.compile(r"/api2/v2/vault/lists/(\d+)"), _delete),
]
