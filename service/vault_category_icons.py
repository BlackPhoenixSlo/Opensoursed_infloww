"""Private artwork shared by an agency's Vault Pro categories."""
from __future__ import annotations

import base64
import io
import json
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from starlette.concurrency import run_in_threadpool

from agency_context import AgencyContext, agency_context
from chatters import allowed_folder_ids_for_chatter
from db.engine import get_session
from db.models import UserSetting

router = APIRouter(prefix="/admin/vault-ai/category-icons")
PREFIX = "vault_category_icon:"
CATEGORIES = frozenset({
    "bare-booty", "bikini-lingerie", "covered-booty", "covered-breast",
    "bare-breast", "feet", "handbra", "long-videos", "customs",
})
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000


async def _context(account_id: str, *, edit: bool = False) -> AgencyContext:
    ctx = await agency_context(account_id=account_id)
    if (edit and not ctx.is_owner) or await allowed_folder_ids_for_chatter(account_id) is not None:
        raise HTTPException(403, "Category icons are outside your folder permissions")
    return ctx


def _slot(category: str) -> str:
    if category not in CATEGORIES:
        raise HTTPException(404, "Unknown folder category")
    return PREFIX + category


def square_thumbnail(data: bytes, x: float, y: float) -> str:
    """Decode the selected still and save only the square crop, without metadata."""
    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as source:
            if source.width * source.height > MAX_PIXELS:
                raise HTTPException(413, "Choose an image below 20 megapixels")
            if getattr(source, "n_frames", 1) != 1:
                raise HTTPException(400, "Choose a still image")
            image = ImageOps.exif_transpose(source).convert("RGB")
            thumbnail = ImageOps.fit(image, (192, 192), Image.Resampling.LANCZOS, centering=(x, y))
            with io.BytesIO() as out:
                thumbnail.save(out, format="WEBP", quality=88)
                return base64.b64encode(out.getvalue()).decode("ascii")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise HTTPException(400, "Choose a valid JPG, PNG or WebP image") from exc


@router.get("")
async def list_icons(response: Response, account_id: str = Query(..., min_length=1)) -> dict:
    ctx = await _context(account_id)
    response.headers["Cache-Control"] = "private, no-store"
    async with get_session() as session:
        rows = (await session.execute(select(UserSetting.tab, UserSetting.config_json).where(
            UserSetting.user_id == ctx.agency_user_id,
            UserSetting.tab.in_([PREFIX + category for category in CATEGORIES]),
        ))).all()
    return {"can_edit": ctx.is_owner, "icons": {
        key.removeprefix(PREFIX): json.loads(value)["webp"] for key, value in rows
    }}


@router.post("/{category}")
async def upload_icon(
    category: str,
    account_id: str = Query(..., min_length=1),
    file: UploadFile = File(...),
    x: float = Form(0.5, ge=0, le=1),
    y: float = Form(0.5, ge=0, le=1),
) -> dict:
    ctx = await _context(account_id, edit=True)
    slot = _slot(category)
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Choose an image below 8 MB")
    thumbnail = await run_in_threadpool(square_thumbnail, data, x, y)
    payload = json.dumps({"webp": thumbnail})
    now = datetime.utcnow()
    async with get_session() as session:
        await session.execute(insert(UserSetting).values(
            user_id=ctx.agency_user_id, tab=slot, config_json=payload, updated_at=now,
        ).on_conflict_do_update(
            index_elements=[UserSetting.user_id, UserSetting.tab],
            set_={"config_json": payload, "updated_at": now},
        ))
    return {"ok": True}


@router.delete("/{category}")
async def reset_icon(category: str, account_id: str = Query(..., min_length=1)) -> dict:
    ctx = await _context(account_id, edit=True)
    slot = _slot(category)
    async with get_session() as session:
        await session.execute(delete(UserSetting).where(
            UserSetting.user_id == ctx.agency_user_id, UserSetting.tab == slot,
        ))
    return {"ok": True}
