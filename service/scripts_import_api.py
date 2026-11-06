"""service/scripts_import_api.py — Growth > Scripts' Excel import and copy between Creators.

  GET  /admin/saved-replies/import-template           → the empty .xlsx template
  POST /admin/saved-replies/import?account_id=  multipart `file`
       → {total, success_count, fail_count, failed: [{sheet, row, name, reason}]}
  POST /admin/saved-replies/copy  {from_account_ids, to_account_ids, ids?}
       → {copied, skipped, media_dropped, sequence_dropped}
  POST /admin/saved-replies/bulk?account_id=  {sequences, tags, mode, dry_run?}
       → {sequences: {...counts}, steps: {...}, tag_scripts: {...}, skipped: [names], failed: [...]}

Bulk is an Infloww library (its sequences with their steps, its tags with their
scripts) in JSON, as `scripts/import_infloww_scripts.py` posts it in chunks:
see `bulk_import`.

Excel import is Infloww's (remote web bundle `FileUpload` / `ImportScript`, the
help article H262073): every sheet is read, its name becomes the scripts' tag,
row 1 is a header naming the `name`, `text` and `note` columns (any order, any
case; a sheet whose header names none of them reads A, B, C), and a row with all
three empty is skipped. A sheet over 1000 rows refuses the whole file, as
Infloww's "Exceeded maximum allowed rows (1000)." does. Limits are the help
article's import limits: name 64, tag 32, text 1000 (as a fan reads it), note 246 characters; name
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
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, func, select

from auth import assert_account_owned
from db.engine import get_session
from db.models import SavedReply, SavedReplySequence
from of_rich_text import of_text, plain_length
from saved_replies_api import prune_sequences
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
    """Why a row fails, or None. `text` (already of_text'd) counts as the fan reads it: markup by its plain text."""
    if not name:
        return "name is required"
    if not plain_length(text):
        return "text is required"
    for label, n, limit in (("name", len(name), NAME_MAX), ("tag", len(tag), TAG_MAX),
                            ("text", plain_length(text), TEXT_MAX), ("note", len(note), NOTE_MAX)):
        if n > limit:
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
            text = of_text(r["text"])  # a cell may hold markup: only OF's allow-list is stored
            reason = _reason(tag, r["name"], text, r["note"])
            if reason is None and _key(r["name"]) in have:
                reason = "duplicate name"
            if reason:
                failed.append({"sheet": r["sheet"], "row": r["row"], "name": r["name"], "reason": reason})
                continue
            have.add(_key(r["name"]))
            s.add(SavedReply(account_id=account_id, title=r["name"], text=text,
                             tags_json=json.dumps([tag] if tag else []), notes=r["note"] or None))
            added += 1
        await s.commit()
    return {"total": len(rows), "success_count": added, "fail_count": len(failed), "failed": failed}


# `assert_account_owned("")` passes, so an empty id must never reach it.
_AccountId = Annotated[str, Field(min_length=1)]


class _CopyBody(BaseModel):
    from_account_ids: list[_AccountId] = Field(..., min_length=1, max_length=_MAX_COPY_SOURCES)
    # The targets to share to. Omitted/empty is only valid with `all_creators`, which
    # resolves the targets SERVER-SIDE to the principal's full owned Creator roster.
    to_account_ids: list[_AccountId] = Field(default_factory=list)
    # Share to every Creator the principal owns (the full roster, not session-only).
    all_creators: bool = False
    # The scripts to copy; omitted copies every script of the sources.
    ids: list[int] | None = None


@router.post("/copy")
async def copy_scripts(body: _CopyBody = Body(...)) -> dict[str, Any]:
    """Share (from a Creator to others) / Import (from others to this Creator).

    Dedup is a true no-op on a re-share: per target it builds `have` from the target's
    held script keys (title, case-blind, or "\\0"+text for an untitled one) and skips any
    source whose key is already there (and the source account itself), adding keys mid-run
    so two sources can't both land. `all_creators` resolves the targets to the owned roster
    (`owned_account_ids`); each resolved id still passes `assert_account_owned`.

    Share-to-all is COMMITTED PER TARGET Creator, so a failure part-way leaves the finished
    targets persisted and a re-run is a no-op for them (the lightest correct "job": the UI
    disables the Confirm button for the single request's life — no separate task table). A
    copied row that introduces a sequence (`script_id`) the target lacks also carries that
    sequence's header: a `SavedReplySequence` upsert, idempotent on unique (account_id, name)
    — never a blind insert, and the target's other sequences are not reordered."""
    from_ids = list(dict.fromkeys(body.from_account_ids))
    if body.all_creators:
        from accounts_admin_api import owned_account_ids
        targets = owned_account_ids()
    else:
        targets = list(dict.fromkeys(body.to_account_ids))
    if not targets:
        raise HTTPException(status_code=422, detail="no target creators")
    for acc in {*from_ids, *targets}:
        assert_account_owned(acc)
    copied = skipped = media_dropped = sequence_dropped = 0
    async with get_session() as s:
        q = (select(SavedReply)
             .where(SavedReply.account_id.in_(from_ids))
             .order_by(SavedReply.id))
        if body.ids is not None:
            q = q.where(SavedReply.id.in_(body.ids))
        # Materialise before the per-target commits so no row is accessed detached.
        sources = [{"account_id": r.account_id, "title": r.title, "text": r.text,
                    "gif_id": r.gif_id, "gif_url": r.gif_url, "script_id": r.script_id,
                    "script_step": r.script_step, "tags_json": r.tags_json, "notes": r.notes,
                    "has_media": bool(json.loads(r.media_json or "[]"))}
                   for r in (await s.execute(q)).scalars().all()]
        # The source sequences' headers (first source to name a sequence wins), carried to a
        # target that lacks the sequence.
        src_metas: dict[str, SavedReplySequence] = {}
        for m in (await s.execute(select(SavedReplySequence).where(
                SavedReplySequence.account_id.in_(from_ids)).order_by(SavedReplySequence.id))).scalars():
            src_metas.setdefault(m.name, m)
        for target in dict.fromkeys(targets):
            held = (await s.execute(select(SavedReply).where(
                SavedReply.account_id == target))).scalars().all()
            have = {_key(r.title) if r.title else "\0" + r.text for r in held}
            steps = {(r.script_id, r.script_step) for r in held if r.script_id}
            # Sequence names the target already keeps a header for: the meta upsert's idempotency.
            meta_names = set((await s.execute(select(SavedReplySequence.name).where(
                SavedReplySequence.account_id == target))).scalars())
            seeded: set[str] = set()
            for src in sources:
                k = _key(src["title"]) if src["title"] else "\0" + src["text"]
                if src["account_id"] == target or k in have:
                    skipped += 1
                    continue
                have.add(k)
                if src["has_media"]:
                    media_dropped += 1
                script_id, script_step = src["script_id"], src["script_step"]
                if script_id and (script_id, script_step) in steps:
                    script_id = script_step = None
                    sequence_dropped += 1
                elif script_id:
                    steps.add((script_id, script_step))
                s.add(SavedReply(
                    account_id=target, title=src["title"], text=src["text"],
                    gif_id=src["gif_id"], gif_url=src["gif_url"],
                    script_id=script_id, script_step=script_step,
                    tags_json=src["tags_json"], notes=src["notes"],
                ))
                copied += 1
                # The surviving sequence the target lacks a header for: carry it once.
                if script_id and script_id not in meta_names and script_id not in seeded:
                    seeded.add(script_id)
                    sm = src_metas.get(script_id)
                    if sm is not None:
                        s.add(SavedReplySequence(
                            account_id=target, name=script_id, description=sm.description,
                            created_by=sm.created_by, position=sm.position))
            await s.commit()
    return {"copied": copied, "skipped": skipped, "media_dropped": media_dropped,
            "sequence_dropped": sequence_dropped}


@router.get("/overview")
async def saved_replies_overview() -> dict[str, Any]:
    """All-models view (read-only): per owned Creator, each sequence's step count and each
    tag's script count, by SQL GROUP BY only — no script text/bodies loaded.

    Shape: {accounts:[{id, nickname}], sequences:[{name, per_account:{id:count}}],
    tags:[{name, per_account:{id:count}}]}. A tag is counted once per script that carries it
    (a script in two tags counts in both). Same /admin/saved-replies prefix, so the Scripts Role gate applies; every
    account is resolved through `owned_account_ids`, each owned."""
    from accounts_admin_api import owned_account_ids
    import accounts as account_registry
    import relay_coalesce
    ids = owned_account_ids()
    for aid in ids:
        assert_account_owned(aid)
    accounts = [{"id": aid, "nickname": (account_registry.get_account(aid) or {}).get("nickname")}
                for aid in ids]
    if not ids:
        return {"accounts": accounts, "sequences": [], "tags": []}

    async def _load() -> dict[str, Any]:
        async with get_session() as s:
            seq_rows = (await s.execute(
                select(SavedReply.account_id, SavedReply.script_id, func.count())
                .where(SavedReply.account_id.in_(ids), SavedReply.script_id.is_not(None))
                .group_by(SavedReply.account_id, SavedReply.script_id))).all()
            tag_rows = (await s.execute(
                select(SavedReply.account_id, SavedReply.tags_json, func.count())
                .where(SavedReply.account_id.in_(ids))
                .group_by(SavedReply.account_id, SavedReply.tags_json))).all()
        sequences: dict[str, dict[str, int]] = {}
        for aid, name, n in seq_rows:
            sequences.setdefault(name, {})[aid] = n
        tags: dict[str, dict[str, int]] = {}
        for aid, tags_json, n in tag_rows:
            for t in json.loads(tags_json or "[]"):
                per = tags.setdefault(t, {})
                per[aid] = per.get(aid, 0) + n
        return {"accounts": accounts,
                "sequences": [{"name": nm, "per_account": per} for nm, per in sorted(sequences.items())],
                "tags": [{"name": nm, "per_account": per} for nm, per in sorted(tags.items())]}

    return await relay_coalesce.coalesce_fresh(("saved_replies_overview", tuple(sorted(ids))), _load)


# ── Bulk import (an Infloww library in JSON) ─────────────────────────
# Limits: the saved-reply editor's (name 64 as SCRIPT_NAME_MAX, notes 256, tag 32, price >= 0) with Infloww's
# text cap (6500) and condition text (150); sequence name 64 as relabel's. A request holds at most BULK_ROWS_MAX
# scripts: the CLI chunks a library, never splitting a sequence.
BULK_TEXT_MAX, BULK_NOTE_MAX, BULK_COND_MAX, SEQ_NAME_MAX = 6500, 256, 150, 64
BULK_BY_MAX, BULK_DESC_MAX = 128, 6500
BULK_ROWS_MAX = 5000
_STEP = re.compile(r"^\s*(\d+)(?:\.(\d+))?\s*$")
_FM = re.compile(r"^FM\d+$")


class _BulkStep(BaseModel):
    step: str | int | float
    text: str | None = None
    notes: str | None = None
    name: str | None = None
    conditional: str | None = None
    price: float | None = None
    # The step script's own tags (Infloww: a sequence step IS a script, and that script may sit in tags).
    tags: list[str] = Field(default_factory=list)


class _BulkSequence(BaseModel):
    name: str
    order: int | None = None
    created_by: str | None = None
    created_on: str | int | float | None = None
    modified_on: str | int | float | None = None
    description: str | None = None
    steps: list[_BulkStep] = Field(default_factory=list)


class _BulkScript(BaseModel):
    name: str | None = None
    text: str | None = None
    notes: str | None = None
    price: float | None = None


class _BulkTag(BaseModel):
    name: str
    order: int | None = None
    scripts: list[_BulkScript] = Field(default_factory=list)


class _BulkBody(BaseModel):
    sequences: list[_BulkSequence] = Field(default_factory=list)
    tags: list[_BulkTag] = Field(default_factory=list)
    mode: Literal["skip", "replace"] = "skip"
    # Run every check and count, then roll back: the CLI's --dry-run.
    dry_run: bool = False


def _parse_step(v: str | int | float) -> tuple[int, int] | None:
    """"3" -> (3, 0), "2.1" -> (2, 1); None below step 1 or not N / N.M."""
    m = _STEP.match(str(v))
    if not m or int(m.group(1)) < 1:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def _ordered_steps(steps: list[_BulkStep]) -> list[tuple[int, _BulkStep]]:
    """A valid sequence's steps as (N, step) in insert order: by N, then option M, then payload order (so a
    step's options get ascending ids, the order the Scripts page and the chat list them in)."""
    ordered = sorted(enumerate(steps), key=lambda e: (_parse_step(e[1].step), e[0]))
    return [(_parse_step(st.step)[0], st) for _, st in ordered]  # type: ignore[index]


def _parse_when(v: str | int | float | None) -> datetime | None:
    """Epoch seconds or ms, an ISO date-time, or Infloww's day-only "Oct 13, 2026" (kept at 12:00 UTC so the
    day reads the same in any browser zone), as naive UTC; None when absent or unreadable."""
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(str(v).strip(), "%b %d, %Y").replace(hour=12)
            except ValueError:
                return None
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    try:
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _script_reason(name: str, text: str, notes: str, price: float | None) -> str | None:
    """`text` (already of_text'd) counts as the fan reads it: markup by its plain text."""
    for label, n, limit in (("name", len(name), NAME_MAX), ("text", plain_length(text), BULK_TEXT_MAX),
                            ("notes", len(notes), BULK_NOTE_MAX)):
        if n > limit:
            return f"{label} longer than {limit} characters"
    if price is not None and price < 0:
        return "price below 0"
    return None


def _sequence_reason(q: _BulkSequence) -> str | None:
    name = q.name.strip()
    if not name:
        return "name is required"
    if len(name) > SEQ_NAME_MAX:
        return f"name longer than {SEQ_NAME_MAX} characters"
    if _FM.match(name):
        return "name is reserved (FM follow-up scripts)"
    if len(q.created_by or "") > BULK_BY_MAX or len(q.description or "") > BULK_DESC_MAX:
        return "created_by or description too long"
    if not q.steps:
        return "no steps"
    seen: set[tuple[int, int]] = set()
    for st in q.steps:
        at = _parse_step(st.step)
        if at is None:
            return f"step {st.step!r}: must be N or N.M with N >= 1"
        if at in seen:
            return f"step {st.step!r}: twice"
        seen.add(at)
        why = _script_reason((st.name or "").strip(), of_text(st.text or ""), (st.notes or "").strip(), st.price)
        if why is None and len((st.conditional or "").strip()) > BULK_COND_MAX:
            why = f"conditional longer than {BULK_COND_MAX} characters"
        if why is None and any(len(t.strip()) > TAG_MAX for t in st.tags):
            why = f"tag name longer than {TAG_MAX} characters"
        if why:
            return f"step {st.step}: {why}"
    return None


@router.post("/bulk")
async def bulk_import(account_id: str = Query(...), body: _BulkBody = Body(...)) -> dict[str, Any]:
    """One chunk of an Infloww library into one Creator, in one transaction, ownership checked once.

    A sequence is created whole (its meta row in `saved_reply_sequences`: position = `order`, Created by,
    description, dates; one script per step, `script_step` = N of "N" / "N.M", options in M order) or not at
    all: any bad step fails the whole sequence with the reason. One whose name the Creator already uses
    (some script carries it) is `skip`ped untouched, or with `replace` its scripts are deleted and the
    payload's put in their place (meta updated). A tag's script is matched on (name, case-blind; text): a
    script that exists already (a sequence step included) gets the tag added, else it is created; so a
    re-run creates nothing. Media is not importable (never in the payload); price is kept. `dry_run` counts
    and rolls back. Same Role gate as the Excel import (the Scripts page's `/admin/saved-replies/`)."""
    assert_account_owned(account_id)
    rows_in = sum(len(q.steps) for q in body.sequences) + sum(len(t.scripts) for t in body.tags)
    if rows_in > BULK_ROWS_MAX:
        raise HTTPException(status_code=413, detail=f"more than {BULK_ROWS_MAX} scripts in one request")
    seq = {"total": len(body.sequences), "created": 0, "skipped": 0, "replaced": 0, "failed": 0}
    steps = {"total": sum(len(q.steps) for q in body.sequences), "created": 0, "deleted": 0}
    tagged = {"total": sum(len(t.scripts) for t in body.tags), "created": 0, "tagged": 0, "skipped": 0,
              "failed": 0}
    skipped_names: list[str] = []
    failed: list[dict[str, Any]] = []
    now = datetime.utcnow()
    async with get_session() as s:
        have = set((await s.execute(select(SavedReply.script_id).where(
            SavedReply.account_id == account_id, SavedReply.script_id.is_not(None)).distinct())).scalars())
        metas = {m.name: m for m in (await s.execute(select(SavedReplySequence).where(
            SavedReplySequence.account_id == account_id))).scalars()}
        in_payload: set[str] = set()
        for q in body.sequences:
            name = q.name.strip()
            why = _sequence_reason(q)
            if why is None and name in in_payload:
                why = "name twice in this request"
            if why:
                seq["failed"] += 1
                failed.append({"kind": "sequence", "name": name, "reason": why})
                continue
            in_payload.add(name)
            if name in have and body.mode == "skip":
                seq["skipped"] += 1
                skipped_names.append(name)
                continue
            if name in have:
                gone = await s.execute(sa_delete(SavedReply).where(SavedReply.account_id == account_id,
                                                                   SavedReply.script_id == name))
                steps["deleted"] += gone.rowcount or 0
                seq["replaced"] += 1
            else:
                seq["created"] += 1
            created = _parse_when(q.created_on) or now
            modified = _parse_when(q.modified_on) or created
            meta = metas.get(name)
            if meta is None:
                meta = metas[name] = SavedReplySequence(account_id=account_id, name=name)
                s.add(meta)
            meta.position, meta.created_by = q.order, (q.created_by or "").strip() or None
            meta.description = (q.description or "").strip() or None
            meta.created_at, meta.updated_at = created, modified
            for n, st in _ordered_steps(q.steps):
                s.add(SavedReply(
                    account_id=account_id, title=(st.name or "").strip() or None, text=of_text(st.text or ""),
                    price_cents=int(round((st.price or 0) * 100)), script_id=name, script_step=n,
                    tags_json=json.dumps(list(dict.fromkeys(t.strip() for t in st.tags if t.strip()))),
                    notes=(st.notes or "").strip() or None,
                    conditional=(st.conditional or "").strip() or None,
                    created_at=created, updated_at=modified,
                ))
                steps["created"] += 1
            have.add(name)
        await s.flush()
        # Tags: (name, text) -> the script that holds it.
        index: dict[tuple[str, str], int] = {}
        for rid, title, text in (await s.execute(
                select(SavedReply.id, SavedReply.title, SavedReply.text)
                .where(SavedReply.account_id == account_id)
                .order_by(SavedReply.id))).all():
            index.setdefault((_key(title), text), rid)
        for t in body.tags:
            tag = t.name.strip()
            for sc in t.scripts:
                # Infloww stores scripts as HTML: only OF's allow-list is kept (plain text as is), and the
                # (name, text) match below compares stored text with stored text.
                name, text, notes = (sc.name or "").strip(), of_text(sc.text or ""), (sc.notes or "").strip()
                why = ("tag name is required" if not tag
                       else f"tag name longer than {TAG_MAX} characters" if len(tag) > TAG_MAX
                       else "name and text are empty" if not name and not text.strip()
                       else _script_reason(name, text, notes, sc.price))
                if why:
                    tagged["failed"] += 1
                    failed.append({"kind": "tag_script", "tag": tag, "name": name, "reason": why})
                    continue
                rid = index.get((_key(name), text))
                if rid is not None:
                    row = await s.get(SavedReply, rid)
                    tags = json.loads(row.tags_json or "[]")
                    if tag in tags:
                        tagged["skipped"] += 1
                    else:
                        row.tags_json = json.dumps([*tags, tag])
                        tagged["tagged"] += 1
                    continue
                row = SavedReply(account_id=account_id, title=name or None, text=text,
                                 price_cents=int(round((sc.price or 0) * 100)), tags_json=json.dumps([tag]),
                                 notes=notes or None)
                s.add(row)
                await s.flush()
                index[(_key(name), text)] = row.id
                tagged["created"] += 1
        await prune_sequences(s, account_id)
        if body.dry_run:
            await s.rollback()
        else:
            await s.commit()
    return {"dry_run": body.dry_run, "mode": body.mode, "sequences": seq, "steps": steps,
            "tag_scripts": tagged, "skipped": skipped_names, "failed": failed}
