"""service/scripts_import_api.py — Growth > Scripts' Excel import and copy between Creators.

  GET  /admin/saved-replies/import-template           → the empty .xlsx template
  POST /admin/saved-replies/import?account_id=  multipart `file`
       → {total, success_count, fail_count, failed: [{sheet, row, name, reason}]}
  POST /admin/saved-replies/copy  {from_account_ids, to_account_ids, ids?}
       → {copied, skipped, media_dropped, sequence_dropped}

Excel import is Infloww's (remote web bundle `FileUpload` / `ImportScript`, the
help article H262073): every sheet is read, its name becomes the scripts' tag,
row 1 is a header naming the `name`, `text` and `note` columns (any order, any
case; a sheet whose header names none of them reads A, B, C), and a row with all
three empty is skipped. A sheet over 1000 rows refuses the whole file, as
Infloww's "Exceeded maximum allowed rows (1000)." does. Limits are the help
article's import limits: name 64, tag 32, text 1000, note 246 characters; name
and text are required. A name the Creator already has, or an earlier row of the
file has, is a failed row ("duplicate name"), never an overwrite.

Copy is Share (from this Creator to others) and Import from other creators (from
others to this one) in one route. A copied script keeps its name, text, tags,
notes, sequence and GIF; media never moves between accounts (ADR-0008), so
media, previews, price and locked text are dropped and counted, and tagged
Creators (an account's own @-tags) are dropped too. A name the target already
has is skipped (an untitled script: the same text). A sequence step the target
already holds (its own, or an earlier copy's: two sources sharing a sequence
name) arrives outside any sequence, counted as `sequence_dropped`, so no
sequence ends up with two scripts at one step.

Every route sits under /admin/saved-replies/, so Role enforcement maps it to the
Scripts page (`permissions.PAGE_MAP`), and each account named goes through
`assert_account_owned`.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from auth import assert_account_owned
from db.engine import get_session
from db.models import SavedReply
from xlsx_io import read_xlsx, write_xlsx

router = APIRouter(prefix="/admin/saved-replies", tags=["scripts"])

NAME_MAX, TAG_MAX, TEXT_MAX, NOTE_MAX = 64, 32, 1000, 246
SHEET_ROWS_MAX = 1000
COLUMNS = ("name", "text", "note")
_HEADER_ALIASES = {"notes": "note"}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_UPLOAD = 5 * 1024 * 1024
_MAX_COPY_SOURCES = 5


def _key(name: str | None) -> str:
    return (name or "").strip().lower()


def _columns(header: dict[int, str]) -> dict[str, int]:
    """Column index of name / text / note from the header row; A, B, C when it names none."""
    found: dict[str, int] = {}
    for i, h in sorted(header.items()):
        k = h.strip().lower()
        k = _HEADER_ALIASES.get(k, k)
        if k in COLUMNS and k not in found:
            found[k] = i
    return found or {c: i for i, c in enumerate(COLUMNS)}


def _reason(tag: str, name: str, text: str, note: str) -> str | None:
    if not name:
        return "name is required"
    if not text:
        return "text is required"
    for label, value, limit in (("name", name, NAME_MAX), ("tag", tag, TAG_MAX),
                                ("text", text, TEXT_MAX), ("note", note, NOTE_MAX)):
        if len(value) > limit:
            return f"{label} longer than {limit} characters"
    return None


def parse_workbook(data: bytes) -> list[dict[str, Any]]:
    """The workbook's script rows: {sheet, row, name, text, note}, row numbers 1-based as Excel shows them.
    ValueError for a file that is not an .xlsx or a sheet over the row limit."""
    out: list[dict[str, Any]] = []
    for sheet, rows in read_xlsx(data):
        filled = [(n, r) for n, r in enumerate(rows, start=1) if any(c.strip() for c in r.values())]
        if len(filled) > SHEET_ROWS_MAX + 1:
            raise ValueError(f"Exceeded maximum allowed rows ({SHEET_ROWS_MAX}) in sheet {sheet!r}.")
        if not filled:
            continue
        cols = _columns(filled[0][1])
        for n, r in filled[1:]:
            cell = {c: (r.get(cols[c], "") if c in cols else "").strip() for c in COLUMNS}
            if any(cell.values()):
                out.append({"sheet": sheet, "row": n, **cell})
    return out


@router.get("/import-template")
async def import_template() -> Response:
    data = write_xlsx([list(COLUMNS)], "Tag 1")
    return Response(content=data, media_type=_XLSX,
                    headers={"Content-Disposition": 'attachment; filename="Script Templates.xlsx"'})


@router.post("/import")
async def import_scripts(account_id: str = Query(...), file: UploadFile = File(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    data = await file.read(_MAX_UPLOAD + 1)
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="the file is larger than 5 MB")
    try:
        rows = parse_workbook(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not rows:
        raise HTTPException(status_code=422, detail="the file holds no scripts")
    failed: list[dict[str, Any]] = []
    added = 0
    async with get_session() as s:
        have = {_key(t) for t in (await s.execute(
            select(SavedReply.title).where(SavedReply.account_id == account_id))).scalars() if t}
        for r in rows:
            tag = r["sheet"].strip()
            reason = _reason(tag, r["name"], r["text"], r["note"])
            if reason is None and _key(r["name"]) in have:
                reason = "duplicate name"
            if reason:
                failed.append({"sheet": r["sheet"], "row": r["row"], "name": r["name"], "reason": reason})
                continue
            have.add(_key(r["name"]))
            s.add(SavedReply(account_id=account_id, title=r["name"], text=r["text"],
                             tags_json=json.dumps([tag] if tag else []), notes=r["note"] or None))
            added += 1
        await s.commit()
    return {"total": len(rows), "success_count": added, "fail_count": len(failed), "failed": failed}


# `assert_account_owned("")` passes, so an empty id must never reach it.
_AccountId = Annotated[str, Field(min_length=1)]


class _CopyBody(BaseModel):
    from_account_ids: list[_AccountId] = Field(..., min_length=1, max_length=_MAX_COPY_SOURCES)
    to_account_ids: list[_AccountId] = Field(..., min_length=1)
    # The scripts to copy; omitted copies every script of the sources.
    ids: list[int] | None = None


@router.post("/copy")
async def copy_scripts(body: _CopyBody = Body(...)) -> dict[str, Any]:
    for acc in {*body.from_account_ids, *body.to_account_ids}:
        assert_account_owned(acc)
    copied = skipped = media_dropped = sequence_dropped = 0
    async with get_session() as s:
        q = select(SavedReply).where(SavedReply.account_id.in_(body.from_account_ids)).order_by(SavedReply.id)
        if body.ids is not None:
            q = q.where(SavedReply.id.in_(body.ids))
        sources = (await s.execute(q)).scalars().all()
        for target in dict.fromkeys(body.to_account_ids):
            held = (await s.execute(select(SavedReply).where(SavedReply.account_id == target))).scalars().all()
            have = {_key(r.title) if r.title else "\0" + r.text for r in held}
            steps = {(r.script_id, r.script_step) for r in held if r.script_id}
            for src in sources:
                k = _key(src.title) if src.title else "\0" + src.text
                if src.account_id == target or k in have:
                    skipped += 1
                    continue
                have.add(k)
                if json.loads(src.media_json or "[]"):
                    media_dropped += 1
                script_id, script_step = src.script_id, src.script_step
                if script_id and (script_id, script_step) in steps:
                    script_id = script_step = None
                    sequence_dropped += 1
                elif script_id:
                    steps.add((script_id, script_step))
                s.add(SavedReply(
                    account_id=target, title=src.title, text=src.text,
                    gif_id=src.gif_id, gif_url=src.gif_url,
                    script_id=script_id, script_step=script_step,
                    tags_json=src.tags_json, notes=src.notes,
                ))
                copied += 1
        await s.commit()
    return {"copied": copied, "skipped": skipped, "media_dropped": media_dropped,
            "sequence_dropped": sequence_dropped}
