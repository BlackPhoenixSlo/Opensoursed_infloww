"""service/sensitive_words_api.py — Growth > Sensitive words, one list per Agency.

Infloww's feature (remote web bundle, menu 87 "/admin/growth/sensitive-words"):
an Agency-wide word list, managed on its own Growth page, that every composer
checks while you type. A hit shows "Input contains prohibited language: [word]"
under the text; the mass message and script editors refuse to send or save
until the text is clean, the one-to-one chat composer only warns. The checking
happens in the app (app/lib/sensitiveWords.ts); this module stores the list.

  GET  /admin/sensitive-words[?account_id=]
       → {words: [str]} sorted A-Z. Any session of the Agency: every composer
         reads it, a chatter's too. A chatter linked to several Agencies that
         names no Creator gets the union of their lists.
  POST /admin/sensitive-words/add     {words: [str]}      → import result
  POST /admin/sensitive-words/update  {old, latest}       → {word}
  POST /admin/sensitive-words/delete  {words: [str]}      → {deleted: n}
  GET  /admin/sensitive-words/export                      → .xlsx of the list
  GET  /admin/sensitive-words/template                    → the empty .xlsx template
  POST /admin/sensitive-words/import  multipart `file`    → import result

The import result is {total, success_count, fail_count, failed: [{word, reason}]}.
A word is trimmed, its inner whitespace collapsed to one space, and must be 1 to
32 characters (Infloww's input limit). Matching is case-insensitive, so the list
holds each word once in any case; a repeat is a failure, not an error.

Every route under /admin/sensitive-words/ is owner session or Master: the
chatter admin gate refuses a chatter 403 (`chatters._CHATTER_BLOCKED_ADMIN_PREFIXES`)
and each handler checks again through `owner_context`. Signed out is 401.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, func, select

from db.engine import get_session
from db.models import SensitiveWord
from employees import agency_contexts, json_object, owner_context
from xlsx_io import read_xlsx, write_xlsx

router = APIRouter(prefix="/admin/sensitive-words", tags=["sensitive-words"])

MAX_LEN = 32
HEADER = "Sensitive Words"
_OWNER_ONLY = "only the agency owner manages Sensitive words"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_UPLOAD = 2 * 1024 * 1024
_MAX_ROWS = 5000


def clean_word(raw: Any) -> str:
    """The stored form of one word: trimmed, inner whitespace one space."""
    return re.sub(r"\s+", " ", raw).strip() if isinstance(raw, str) else ""


def _reason(word: str) -> str | None:
    if not word:
        return "empty"
    if len(word) > MAX_LEN:
        return f"longer than {MAX_LEN} characters"
    return None


async def _owner():
    return await owner_context(None, _OWNER_ONLY)


async def _add(agency_user_id: str, raw_words: list[Any]) -> dict[str, Any]:
    failed: list[dict[str, str]] = []
    added = 0
    async with get_session() as s:
        have = set((await s.execute(
            select(SensitiveWord.word_key).where(SensitiveWord.agency_user_id == agency_user_id)
        )).scalars())
        for raw in raw_words:
            word = clean_word(raw)
            reason = _reason(word) or ("already in the list" if word.lower() in have else None)
            if reason:
                failed.append({"word": word if word else str(raw or ""), "reason": reason})
                continue
            have.add(word.lower())
            s.add(SensitiveWord(agency_user_id=agency_user_id, word=word, word_key=word.lower()))
            added += 1
    return {"total": len(raw_words), "success_count": added, "fail_count": len(failed), "failed": failed}


def _word_list(body: dict[str, Any]) -> list[Any]:
    words = body.get("words")
    if not isinstance(words, list) or not words:
        raise HTTPException(status_code=422, detail="words must be a non-empty list")
    return words


@router.get("")
async def list_words(account_id: str | None = Query(None)) -> dict[str, Any]:
    agencies = [c.agency_user_id for c in await agency_contexts(account_id=account_id)]
    async with get_session() as s:
        words = (await s.execute(
            select(SensitiveWord.word).where(SensitiveWord.agency_user_id.in_(agencies))
        )).scalars().all()
    unique = {w.lower(): w for w in words}
    return {"words": sorted(unique.values(), key=str.lower)}


@router.post("/add")
async def add_words(request: Request) -> dict[str, Any]:
    ctx = await _owner()
    return await _add(ctx.agency_user_id, _word_list(await json_object(request, 422)))


@router.post("/update")
async def update_word(request: Request) -> dict[str, Any]:
    ctx = await _owner()
    body = await json_object(request, 422)
    old, latest = clean_word(body.get("old")), clean_word(body.get("latest"))
    if reason := _reason(latest):
        raise HTTPException(status_code=422, detail=f"latest is {reason}")
    async with get_session() as s:
        mine = select(SensitiveWord).where(SensitiveWord.agency_user_id == ctx.agency_user_id)
        row = (await s.execute(mine.where(SensitiveWord.word_key == old.lower()))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"{old!r} is not in the list")
        if latest.lower() != row.word_key:
            clash = (await s.execute(mine.where(SensitiveWord.word_key == latest.lower()))).first()
            if clash is not None:
                raise HTTPException(status_code=409, detail=f"{latest!r} is already in the list")
        row.word, row.word_key = latest, latest.lower()
    return {"word": latest}


@router.post("/delete")
async def delete_words(request: Request) -> dict[str, Any]:
    ctx = await _owner()
    keys = {clean_word(w).lower() for w in _word_list(await json_object(request, 422))}
    async with get_session() as s:
        r = await s.execute(delete(SensitiveWord).where(
            SensitiveWord.agency_user_id == ctx.agency_user_id, SensitiveWord.word_key.in_(keys)))
    return {"deleted": r.rowcount or 0}


def _xlsx_response(words: list[str], filename: str) -> Response:
    return Response(content=write_column([HEADER, *words]), media_type=_XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export")
async def export_words() -> Response:
    ctx = await _owner()
    async with get_session() as s:
        words = (await s.execute(
            select(SensitiveWord.word).where(SensitiveWord.agency_user_id == ctx.agency_user_id)
            .order_by(func.lower(SensitiveWord.word))
        )).scalars().all()
    return _xlsx_response(list(words), "Sensitive Words.xlsx")


@router.get("/template")
async def template() -> Response:
    await _owner()
    return _xlsx_response([], "Sensitive Words Templates.xlsx")


@router.post("/import")
async def import_words(file: UploadFile = File(...)) -> dict[str, Any]:
    ctx = await _owner()
    data = await file.read(_MAX_UPLOAD + 1)
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="the file is larger than 2 MB")
    try:
        rows = read_xlsx_first_column(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    words = [w for w in rows[1:] if w.strip()][:_MAX_ROWS]  # row 1 is the header
    if not words:
        raise HTTPException(status_code=422, detail="the file holds no sensitive words")
    return await _add(ctx.agency_user_id, words)


def write_column(column: list[str]) -> bytes:
    """A one-sheet workbook with `column` down column A."""
    return write_xlsx([[v] for v in column], HEADER)


def read_xlsx_first_column(data: bytes) -> list[str]:
    """Column A of the workbook's first sheet, one string per row in order
    (a row with no A cell reads ""). ValueError when `data` is not an .xlsx."""
    sheets = read_xlsx(data, first_only=True)
    return [row.get(0, "") for row in sheets[0][1]] if sheets else []
