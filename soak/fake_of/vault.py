"""Vault reads of the fake OnlyFans (Phase 6 ticket 94: the vault thumbnails read proof).

Mounted from app.py:
  GET  /vault/lists     folders + the whole vault's counts (service/of_reads.py `vault_lists`)
  GET  /vault/lists/{id}   one folder, its listing row, else 404 (the path in OF's own JS,
                        .scratch/ofm-not-yet/captures/of-js-endpoints.txt:593; read by the harness's Relay to confirm a
                        lost reply's folder, relay_live `READ_BACK`). ASSUMPTION: OF answers the listing's folder row
                        (no capture of its answer, inferred per D29); overturned by that capture
  GET  /vault/media     media, paged, `list` = all | a folder id (of_reads `vault_media`)
  POST /vault/lists/sort   the folder sort (ticket 96): `{customOrder, sort: "custom"}` stores a custom order, `{sort,
                        order}` picks a sort (service/of_sends.py `set_vault_lists_custom_order`, `sort_vault_lists`)
  GET  /cdn/{path}      the media's picture bytes: the stand-in for OF's CDN (unsigned, outside /api2/v2)
  POST   /vault/lists       `{name}` creates a custom folder (service/of_sends.py `create_vault_list`)
  PATCH  /vault/lists/{id}  `{name}` renames a created folder (of_sends `rename_vault_list`)
  DELETE /vault/lists/{id}  `{clearMedia}` deletes a created folder (of_sends `delete_vault_list`)

Shapes start from the captured fixtures vault-media-all.json and vault-lists.json (app/lib/__fixtures__/of), ids and
urls replaced. Every picture url is on `CDN_HOST`, a host the Relay's `/img` allows (`.ofcdn.com`,
service/of_client.py `OF_CDN_SUFFIXES`) and nothing here ever reaches: the harness's Relay rewrites it to this fake's
`/cdn` (scripts/of-live-proof/relay_live.py), the Live guard refuses it as not onlyfans.com if it is not rewritten,
and the app browser aborts every non-loopback request.
The folder sort (ticket 96): the fake starts on a stored custom order (sort "custom", not the default order), GET
/vault/lists answers the folders in it, paged, with its `sort` and `order`.
Folder writes (ofm-not-yet ticket 34, the folder page's More proofs): kept in memory per FakeOF instance, applied
before the reply, so the next GET /vault/lists shows them (after the soak folders; last in a custom order that does
not name them). Only folders this instance created can be renamed or deleted; any other id is 404. The replies are
the fake's own (no capture of OF's), in of_sends' documented shapes: the folder dict, and `{success: true}`.
"""
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
from soak.fake_of.growth import _body, _not_found, _write   # one copy of the fake's write helpers
from soak.world import iso, now_utc

CDN_HOST = "fake-cdn.ofcdn.com"
MEDIA_COUNT = 24   # one full page (limit 24), as live: most tiles sit below the fold, lazy (vault--thumbnails)
_FOLDER = "Soak folder"
_STATE = "_soak_vault_folders"
_NEXT = "_soak_vault_folder_n"   # the last folder number taken (FOLDERS: the seeded folders)


def _png(side: int = 8) -> bytes:
    """A small grey PNG, so a tile has a real picture (naturalWidth > 0)."""
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
    """The folders in the default order: the fixture's own rows, its custom folders replaced by FOLDERS soak folders
    (folder 1 holds the media) at the place the first one held."""
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


# ── the folder sort (ticket 96) ──

FOLDERS = 3
# The sorts and orders of_sends.sort_vault_lists' docstring names (CONFIRMED there).
SORTS = ("name", "recent", "media", "custom", "default")
ORDERS = ("asc", "desc")


def order_state(fake) -> dict[str, Any]:
    """This fake's folder sort: {sort, order, custom (stored custom order, folder ids)}. It starts on a stored custom
    order that is not the default one (the last soak folder first), so a Save and its restore both show."""
    st = getattr(fake, "_vault_order", None)
    if st is None:
        default = [r["id"] for r in _rows(render._tpl("vault-lists.json"))]
        last = ids.vault_list_id(FOLDERS)
        st = {"sort": "custom", "order": "desc", "custom": [last, *(i for i in default if i != last)]}
        fake._vault_order = st
    return st


def _sorted(rows: list[dict[str, Any]], st: dict[str, Any]) -> list[dict[str, Any]]:
    """`rows` in the stored custom order (any folder it misses after, in the default order), else the default order,
    reversed for `asc`. As OF's, the order is off for a custom order."""
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
    rows[3 + FOLDERS:3 + FOLDERS] = [dict(f) for f in _created(fake)]   # ticket 34: the folders this fake made
    rows = _sorted(rows, st)
    d["list"] = rows[off:off + lim]
    d["all"] = {"videosCount": 0, "photosCount": MEDIA_COUNT, "gifsCount": 0, "audiosCount": 0, "medias": _covers()}
    d["hasMore"] = off + len(d["list"]) < len(rows)
    d["sort"], d["order"] = st["sort"], st["order"]
    return ok(req, d)


async def _sort(fake, req: Request, ok) -> Response:
    """POST /vault/lists/sort: exactly one of the two bodies the Relay sends, else 400. The answer is
    `{"success": true}` (of_sends' other vault list writes' documented answer; the Relay reads none)."""
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
    if every:   # ticket 97: filed uploads first, hidden items gone (soak/fake_of/posts.py)
        from soak.fake_of import posts as _posts
        items = _posts.listed(fake, items)
    if p.get("sort") == "asc":
        items.reverse()
    page = items[off:off + lim]
    return ok(req, {"list": page, "hasMore": off + len(page) < len(items)})


def _created(fake) -> list[dict[str, Any]]:
    """The folders this FakeOF instance created, oldest first (its own state)."""
    return fake.__dict__.setdefault(_STATE, [])


async def _one(fake, req: Request, ok, fid: str) -> Response:
    rows = [*_rows(render._tpl("vault-lists.json")), *_created(fake)]
    folder = next((f for f in rows if str(f["id"]) == fid), None)
    return ok(req, dict(folder)) if folder else ok(req, {"error": {"code": 0, "message": "Not found"}}, 404)


def _name(body: Any) -> str:
    return str((body if isinstance(body, dict) else {}).get("name") or "")


async def _create(fake, req: Request, ok) -> Response:
    body = await _body(req)
    fake.__dict__[_NEXT] = fake.__dict__.get(_NEXT, FOLDERS) + 1   # never reused, as OF's ids
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
    ("POST", re.compile(r"/api2/v2/vault/lists/sort"), _sort),   # ticket 96
    ("GET", re.compile(r"/api2/v2/vault/lists"), _lists),
    ("GET", re.compile(r"/api2/v2/vault/lists/(\d+)"), _one),          # ofm-not-yet p6p4: the found-id read-back
    ("GET", re.compile(r"/api2/v2/vault/media"), _media),
    ("POST", re.compile(r"/api2/v2/vault/lists"), _create),          # ticket 34
    ("PATCH", re.compile(r"/api2/v2/vault/lists/(\d+)"), _rename),
    ("DELETE", re.compile(r"/api2/v2/vault/lists/(\d+)"), _delete),
]
