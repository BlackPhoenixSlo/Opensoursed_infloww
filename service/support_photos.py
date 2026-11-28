from __future__ import annotations

import io
from typing import Any

import anyio
from fastapi import HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile

MAX_PHOTOS = 4
MAX_PHOTO_BYTES = 3 * 1024 * 1024
MAX_SIDE = 2048
MAX_PIXELS = int(MAX_SIDE * MAX_SIDE * 1.1)
UPLOAD_CAP = MAX_PHOTOS * MAX_PHOTO_BYTES + 64 * 1024
ONLY_PHOTOS = "Only photos (JPEG) can be sent."
TOO_BIG = "Upload too large — max 4 photos of 3 MB."
PHOTO_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'",
                 "Cache-Control": "private, max-age=86400", "Vary": "Cookie, Authorization", "Content-Disposition": "inline"}

Photo = tuple[bytes, int, int]

_decode_slots = anyio.Semaphore(2)


def _reencode(raw: bytes) -> Photo:
    try:
        with Image.open(io.BytesIO(raw), formats=["JPEG"]) as im:
            w, h = im.size
            if w < 1 or h < 1 or w * h > MAX_PIXELS:
                raise HTTPException(status_code=400, detail="Photo is too large — max 2048 px a side.")
            out = ImageOps.exif_transpose(im).convert("RGB")
        out.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=85)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail=ONLY_PHOTOS) from None
    return buf.getvalue(), out.width, out.height


async def reencode(raw: bytes) -> Photo:
    async with _decode_slots:
        return await run_in_threadpool(_reencode, raw)


async def capped_form(request: Request, *, max_fields: int, cap: int = UPLOAD_CAP) -> FormData:
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > cap):
        raise HTTPException(status_code=413, detail=TOO_BIG)
    seen = 0
    receive = request.receive

    async def counted() -> dict[str, Any]:
        nonlocal seen
        msg = await receive()
        if msg["type"] == "http.request":
            seen += len(msg.get("body", b""))
            if seen > cap:
                raise HTTPException(status_code=413, detail=TOO_BIG)
        return msg
    return await Request(request.scope, counted).form(max_files=MAX_PHOTOS, max_fields=max_fields)


async def read_photos(form: FormData) -> list[bytes]:
    parts = form.getlist("photos")
    if len(parts) > MAX_PHOTOS:
        raise HTTPException(status_code=400, detail="Up to 4 photos per message.")
    out: list[bytes] = []
    for part in parts:
        if not isinstance(part, UploadFile):
            raise HTTPException(status_code=400, detail=ONLY_PHOTOS)
        data = await part.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Each photo can be at most 3 MB.")
        out.append(data)
    return out


def form_text(form: FormData, key: str, limit: int) -> str:
    value = form.get(key) or ""
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{key} must be text")
    if len(value) > limit:
        raise HTTPException(status_code=400, detail=f"{key} is too long")
    return value


def photo_response(data: bytes) -> Response:
    return Response(bytes(data), media_type="image/jpeg", headers=PHOTO_HEADERS)
