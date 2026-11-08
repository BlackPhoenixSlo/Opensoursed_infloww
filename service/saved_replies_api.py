"""service/saved_replies_api.py — server.py's saved-replies block, moved
wholesale: local-DB saved replies (Growth > Scripts) CRUD plus tag/sequence relabel.

  GET/POST    /admin/saved-replies
  PUT/DELETE  /admin/saved-replies/{reply_id}
  POST        /admin/saved-replies/relabel
  GET         /admin/saved-replies/sequences   each sequence's own fields (position, Created by, dates)
  POST        /admin/saved-replies/delete      {ids}: a selection in one request
  POST        /admin/saved-replies/sent        {id}: one successful chat send rode this script

A sequence is its scripts' shared `script_id` (the join by name); `saved_reply_sequences` holds its own
fields when it has them (the bulk import, `scripts_import_api.py`). A whole-sequence rename / delete through
relabel moves or drops that row, and a row no script names any more is pruned (`prune_sequences`).

Import/copy (`/admin/saved-replies/import*`, `/copy`) live in scripts_import_api.py.
Included mid-file in server.py for route order (pinned by
service/tests/test_route_order.py).
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Response
from pydantic import BaseModel, Field

import relay_coalesce
from auth import assert_account_owned
from of_rich_text import MARKUP_MAX, PLAIN_MAX, drops_all_text, of_text, plain_length

router = APIRouter()

# A script's notes and a Condition step option's text: the editor's limits, the bulk import's too.
NOTES_MAX, CONDITIONAL_MAX = 256, 150


# ── Saved replies (local-only "templates" minus welcome) ──────────────
# OF's /messages/templates rejects creates for everything except the
# welcome slot. We keep regular saved replies in the local DB and let
# the UI merge them with OF's welcome at render time.

class _SavedReplyBody(BaseModel):
    title: str | None = None
    # 422 past MARKUP_MAX before it is read at all; _clean_text's 400s count the text a fan reads.
    text: str = Field(..., max_length=MARKUP_MAX)
    price: float = Field(0, ge=0)
    locked_text: bool = False
    # Vault-media references, persisted as JSON so the editor can
    # re-render thumbs without a second fetch.
    media: list[dict] = Field(default_factory=list)
    # OF user ids of creators to @-tag when this template is applied.
    # Persisted so the picker can re-hydrate tagging without re-querying
    # OF's tagged-friend-users endpoint on every pick.
    tagged_users: list[int] = Field(default_factory=list)
    # Subset of `media`'s vault ids that ride along UNLOCKED when `price > 0`.
    # Order does not matter; OF treats this as a set.
    previews: list[int] = Field(default_factory=list)
    # Optional Giphy id stored on the template. NULL/None = no GIF. When set,
    # the picker seeds the composer's picked-GIF state on pick so the GIF
    # rides along on send.
    gif_id: str | None = None
    # Cached animated preview URL so the picker chip can render without a
    # fresh Giphy roundtrip.
    gif_url: str | None = None
    # Optional script grouping: when both `script_id` (free-text name) and
    # `script_step` (1-based order) are set, sending this template advances
    # a per-chat cursor; the composer then surfaces the next step in the
    # same script as a one-tap suggestion bubble. NULL on either field opts
    # the template out of the script flow.
    script_id: str | None = None
    script_step: int | None = None
    # Growth > Scripts' tags (names, at most 32 characters each) and internal
    # notes (at most 256). None leaves a stored value as it is on PUT, so a
    # client that predates them never wipes them.
    tags: list[str] | None = None
    notes: str | None = Field(None, max_length=NOTES_MAX)
    # A Condition step option's text (Infloww's `conditional`); None leaves it on PUT.
    conditional: str | None = Field(None, max_length=CONDITIONAL_MAX)


TAG_MAX = 32  # a script tag name (the editor, relabel, the Excel and bulk imports)
IN_CHUNK = 500  # ids per `IN (...)`: under SQLite's bound-variable cap
IDS_MAX = 20_000  # ids in one selection request


async def prune_sequences(s: Any, account_id: str) -> None:
    """Drop the account's sequence rows no script names any more (deleted, ungrouped or moved out)."""
    from db.models import SavedReply, SavedReplySequence
    from sqlalchemy import delete, select
    named = select(SavedReply.script_id).where(SavedReply.account_id == account_id,
                                                SavedReply.script_id.is_not(None))
    await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id == account_id,
                                                     SavedReplySequence.name.not_in(named)))


async def touch_sequences(s: Any, account_id: str, names: Iterable[str | None]) -> None:
    """A step of these sequences changed: their Last modified on is now."""
    from datetime import datetime as _dt

    from db.models import SavedReplySequence
    from sqlalchemy import update
    named = {n for n in names if n}
    if named:
        await s.execute(update(SavedReplySequence).where(
            SavedReplySequence.account_id == account_id, SavedReplySequence.name.in_(named),
        ).values(updated_at=_dt.utcnow()))


async def sync_sequences(s: Any, account_id: str, touched: Iterable[str | None] = ()) -> None:
    """After a script write: flush, mark the `touched` sequences modified now, drop the metas no script names."""
    await s.flush()
    await touch_sequences(s, account_id, touched)
    await prune_sequences(s, account_id)


def _clean_tags(tags: list[str]) -> list[str]:
    """Trimmed, de-duplicated (first spelling wins), empty names dropped; 400 over 32 characters."""
    out: list[str] = []
    for t in tags:
        name = str(t).strip()
        if not name or name in out:
            continue
        if len(name) > TAG_MAX:
            raise HTTPException(status_code=400, detail=f"tag name over {TAG_MAX} characters")
        out.append(name)
    return out


def text_reason(raw: str, text: str) -> str | None:
    """Why a script's text is refused, or None. `text` is `of_text(raw)`, what is stored: refused when the
    allow-list keeps nothing a fan would read of markup that held text (`drops_all_text`; OF's own empty markup,
    a media-only script's, is not that), or past OF's limit counted on the text a fan reads (the editor's counter,
    app/lib/ofRichTextEditor.ts). The editor's routes and the bulk import share it."""
    if drops_all_text(raw, text):
        return "text is only markup that is not kept (nothing a fan would read)"
    if plain_length(text) > PLAIN_MAX:
        return f"text longer than {PLAIN_MAX} characters"
    return None


def _clean_text(raw: str) -> str:
    """The text a script stores: markup reduced to OF's allow-list (of_rich_text), so no client stores other
    HTML; 400 for a `text_reason`."""
    text = of_text(raw)
    if (why := text_reason(raw, text)) is not None:
        raise HTTPException(status_code=400, detail=why)
    return text


def _serialize_saved_reply(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "title": row.title,
        "text": row.text,
        "price": (row.price_cents or 0) / 100,
        "locked_text": bool(row.locked_text),
        "media": json.loads(row.media_json or "[]"),
        "tagged_users": json.loads(getattr(row, "tagged_users_json", None) or "[]"),
        "previews": json.loads(getattr(row, "previews_json", None) or "[]"),
        "gif_id": getattr(row, "gif_id", None),
        "gif_url": getattr(row, "gif_url", None),
        "script_id": getattr(row, "script_id", None),
        "script_step": getattr(row, "script_step", None),
        "tags": json.loads(getattr(row, "tags_json", None) or "[]"),
        "notes": getattr(row, "notes", None),
        "conditional": getattr(row, "conditional", None),
        "sent_count": getattr(row, "sent_count", None) or 0,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/admin/saved-replies", response_model=dict[str, Any])
async def admin_saved_replies_list(account_id: str = Query(...)) -> Response:
    """Saved replies for one account. Sorted newest-edit first.

    Each row also carries `removed_media_ids`: its media our vault mirror has
    since marked deleted on OF (`vault_items.removed_at`), so the composer can
    warn before a chatter sends a script whose media is gone.

    Concurrent reads of one account share one DB read and one JSON encoding
    (`relay_coalesce.coalesce_fresh`, which never hands out a read that started
    before the call, so a list right after a write shows it): 200 owners opening
    a 1.8k-script library at once queued 200 sessions on the pool and timed out
    (slop `2026-11-06-scripts-library`, medium)."""
    assert_account_owned(account_id)
    body = await relay_coalesce.coalesce_fresh(("saved_replies_list", account_id),
                                               lambda: _list_body(account_id))
    return Response(body, media_type="application/json")


async def _list_body(account_id: str) -> bytes:
    """The list's encoded JSON body; the session closes before the rows are encoded."""
    from db.engine import get_session
    from db.models import SavedReply, VaultItem
    from sqlalchemy import select
    async with get_session() as s:
        result = await s.execute(
            select(SavedReply)
            .where(SavedReply.account_id == account_id)
            .order_by(SavedReply.updated_at.desc()),
        )
        rows = result.scalars().all()
        out = [_serialize_saved_reply(r) for r in rows]
        ids_by_row = [[int(m["id"]) for m in r["media"]
                       if isinstance(m, dict) and str(m.get("id", "")).isdigit()] for r in out]
        media_ids = sorted({i for ids in ids_by_row for i in ids})
        removed: set[int] = set()
        # In chunks: a 10k-script library can name more media than SQLite's bound-variable cap.
        for at in range(0, len(media_ids), IN_CHUNK):
            removed.update((await s.execute(
                select(VaultItem.media_id).where(
                    VaultItem.account_id == account_id,
                    VaultItem.media_id.in_(media_ids[at:at + IN_CHUNK]),
                    VaultItem.removed_at.is_not(None),
                ),
            )).scalars().all())
    for r, ids in zip(out, ids_by_row):
        r["removed_media_ids"] = [i for i in ids if i in removed]
    # JSONResponse's own encoding.
    return json.dumps({"list": out}, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


@router.post("/admin/saved-replies")
async def admin_saved_replies_create(
    body: _SavedReplyBody = Body(...),
    account_id: str = Query(...),
) -> dict[str, Any]:
    """Create a new saved reply for an account."""
    assert_account_owned(account_id)
    text = _clean_text(body.text)
    from db.engine import get_session
    from db.models import SavedReply
    async with get_session() as s:
        row = SavedReply(
            account_id=account_id,
            title=body.title,
            text=text,
            price_cents=int(round(body.price * 100)),
            locked_text=body.locked_text,
            media_json=json.dumps(body.media),
            tagged_users_json=json.dumps([int(u) for u in body.tagged_users]),
            previews_json=json.dumps([int(p) for p in body.previews]),
            gif_id=body.gif_id or None,
            gif_url=body.gif_url or None,
            script_id=body.script_id or None,
            script_step=body.script_step,
            tags_json=json.dumps(_clean_tags(body.tags or [])),
            notes=body.notes or None,
            conditional=body.conditional or None,
        )
        s.add(row)
        await sync_sequences(s, account_id, {row.script_id})
        await s.commit()
        await s.refresh(row)
        return _serialize_saved_reply(row)


@router.put("/admin/saved-replies/{reply_id}")
async def admin_saved_replies_update(
    reply_id: int,
    body: _SavedReplyBody = Body(...),
) -> dict[str, Any]:
    """Replace a saved reply's contents wholesale (no PATCH semantics — UI
    submits the full draft on every save, matching the editor's mental model)."""
    from db.engine import get_session
    from db.models import SavedReply
    from datetime import datetime as _dt
    async with get_session() as s:
        row = await s.get(SavedReply, reply_id)
        if not row:
            raise HTTPException(status_code=404, detail="saved reply not found")
        # Defense-in-depth: the row's account_id must be in the active
        # principal's allowed set. Without this, a chatter linked to
        # @alice could PUT a reply that belongs to @bob just by guessing
        # the reply_id.
        assert_account_owned(row.account_id)
        was_in = row.script_id
        row.title = body.title
        row.text = _clean_text(body.text)
        row.price_cents = int(round(body.price * 100))
        row.locked_text = body.locked_text
        row.media_json = json.dumps(body.media)
        row.tagged_users_json = json.dumps([int(u) for u in body.tagged_users])
        row.previews_json = json.dumps([int(p) for p in body.previews])
        row.gif_id = body.gif_id or None
        row.gif_url = body.gif_url or None
        row.script_id = body.script_id or None
        row.script_step = body.script_step
        if body.tags is not None:
            row.tags_json = json.dumps(_clean_tags(body.tags))
        if body.notes is not None:
            row.notes = body.notes or None
        if body.conditional is not None:
            row.conditional = body.conditional or None
        row.updated_at = _dt.utcnow()
        await sync_sequences(s, row.account_id, {was_in, row.script_id})
        await s.commit()
        await s.refresh(row)
        return _serialize_saved_reply(row)


@router.delete("/admin/saved-replies/{reply_id}")
async def admin_saved_replies_delete(reply_id: int) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import SavedReply
    async with get_session() as s:
        row = await s.get(SavedReply, reply_id)
        if row is not None:
            # Same row-based ownership check as PUT.
            assert_account_owned(row.account_id)
        if not row:
            raise HTTPException(status_code=404, detail="saved reply not found")
        await s.delete(row)
        await sync_sequences(s, row.account_id, {row.script_id})
        await s.commit()
        return {"ok": True}


class _IdsBody(BaseModel):
    ids: list[int] = Field(..., max_length=IDS_MAX)


@router.post("/admin/saved-replies/delete")
async def admin_saved_replies_delete_many(
    body: _IdsBody = Body(...),
    account_id: str = Query(...),
) -> dict[str, Any]:
    """Delete a selection in one request (Growth > Scripts' selection bar): this account's rows among `ids`;
    another account's ids are ignored, never an error. Role enforcement gates it as Delete scripts
    (`permissions.ACTIONS["delete-script"]`)."""
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReply
    from sqlalchemy import delete, select
    ids = sorted(set(body.ids))
    deleted = 0
    async with get_session() as s:
        seqs: set[str | None] = set()
        for at in range(0, len(ids), IN_CHUNK):
            where = (SavedReply.account_id == account_id, SavedReply.id.in_(ids[at:at + IN_CHUNK]))
            seqs.update((await s.execute(select(SavedReply.script_id).where(*where))).scalars().all())
            deleted += (await s.execute(delete(SavedReply).where(*where))).rowcount or 0
        await sync_sequences(s, account_id, seqs)
        await s.commit()
    return {"deleted": deleted}


class _SentBody(BaseModel):
    id: int


@router.post("/admin/saved-replies/sent")
async def admin_saved_replies_sent(body: _SentBody = Body(...)) -> dict[str, Any]:
    """An immediate chat send that rode this script went out (the Composer, once OF took it): `sent_count`
    + 1, Growth > Scripts' orange send box. A scheduled send is not counted. Role enforcement maps it to the
    pages whose Composer sends (`permissions`), not to Scripts alone."""
    from db.engine import get_session
    from db.models import SavedReply
    from sqlalchemy import update
    async with get_session() as s:
        row = await s.get(SavedReply, body.id)
        if row is None:
            raise HTTPException(status_code=404, detail="saved reply not found")
        assert_account_owned(row.account_id)
        await s.execute(update(SavedReply).where(SavedReply.id == body.id)
                        .values(sent_count=SavedReply.sent_count + 1))
        await s.commit()
        await s.refresh(row)
        return {"id": row.id, "sent_count": row.sent_count}


@router.get("/admin/saved-replies/sequences")
async def admin_saved_reply_sequences(account_id: str = Query(...)) -> dict[str, Any]:
    """Each sequence's own fields where it has them: {list: [{name, position, created_by, description,
    created_at, updated_at}]}. A sequence missing here is still one (its scripts' `script_id`)."""
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReplySequence
    from sqlalchemy import select
    async with get_session() as s:
        rows = (await s.execute(select(SavedReplySequence).where(
            SavedReplySequence.account_id == account_id).order_by(SavedReplySequence.id))).scalars().all()

    def iso(d: Any) -> str | None:
        return d.isoformat() if d else None

    return {"list": [{"name": r.name, "position": r.position, "created_by": r.created_by,
                      "description": r.description, "created_at": iso(r.created_at),
                      "updated_at": iso(r.updated_at)} for r in rows]}


class _SavedReplyRelabelBody(BaseModel):
    """One tag or sequence edit across an account's scripts (Growth > Scripts).

    - tag, from X, to Y: rename X to Y (merging into Y if it exists); to null deletes X from every script.
    - tag, from null, to Y, ids: add Y to those scripts (the selection bar's "Add to tag").
    - sequence, from X, to Y: rename the sequence (409 if Y is another sequence's name); to null ungroups its
      scripts (script_id and script_step cleared; the scripts themselves stay). The sequence's own row
      (`saved_reply_sequences`) follows a whole-sequence rename and goes with a whole-sequence delete.
    `ids` limits any of these to those scripts (e.g. removing one script from a tag or sequence)."""
    kind: Literal["tag", "sequence"]
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    ids: list[int] | None = None


@router.post("/admin/saved-replies/relabel")
async def admin_saved_replies_relabel(
    body: _SavedReplyRelabelBody = Body(...),
    account_id: str = Query(...),
) -> dict[str, Any]:
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReply
    from sqlalchemy import select
    src = (body.from_ or "").strip() or None
    dst = (body.to or "").strip() or None
    if src is None and (dst is None or body.kind == "sequence" or not body.ids):
        raise HTTPException(status_code=400, detail="from is required, or to and ids to add a tag")
    if body.kind == "tag" and dst is not None and len(dst) > TAG_MAX:
        raise HTTPException(status_code=400, detail=f"tag name over {TAG_MAX} characters")
    if body.kind == "sequence" and dst is not None and len(dst) > 64:
        raise HTTPException(status_code=400, detail="sequence name over 64 characters")
    async with get_session() as s:
        q = select(SavedReply).where(SavedReply.account_id == account_id)
        if body.ids is not None:
            q = q.where(SavedReply.id.in_(body.ids))
        rows = (await s.execute(q)).scalars().all()
        updated = 0
        if body.kind == "tag":
            for row in rows:
                tags = json.loads(row.tags_json or "[]")
                if src is not None:
                    if src not in tags:
                        continue
                    tags = [t for t in tags if t != src]
                if dst is not None and dst not in tags:
                    tags.append(dst)
                row.tags_json = json.dumps(tags)
                updated += 1
        else:
            if dst is not None and dst != src:
                clash = (await s.execute(
                    select(SavedReply.id).where(SavedReply.account_id == account_id,
                                                SavedReply.script_id == dst).limit(1)
                )).first()
                if clash:
                    raise HTTPException(status_code=409, detail="Sequence name already exists. Please rename sequence.")
            for row in rows:
                if row.script_id != src:
                    continue
                row.script_id = dst
                if dst is None:
                    row.script_step = None
                updated += 1
            if src is not None:
                await _relabel_sequence_row(s, account_id, src, dst, whole=body.ids is None)
        await s.commit()
        return {"updated": updated}


async def _relabel_sequence_row(s: Any, account_id: str, src: str, dst: str | None, *, whole: bool) -> None:
    """The sequence's own row after a relabel: a whole rename moves it to `dst` (first dropping a stale row of
    that name: no script carries `dst`, or the clash check would have refused), a whole delete drops it; moving
    some scripts touches both. Then rows no script names go."""
    from datetime import datetime as _dt

    from db.models import SavedReplySequence
    from sqlalchemy import delete, select
    await s.flush()
    if whole and dst is not None and dst != src:
        await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id == account_id,
                                                         SavedReplySequence.name == dst))
        meta = (await s.execute(select(SavedReplySequence).where(
            SavedReplySequence.account_id == account_id, SavedReplySequence.name == src))).scalar_one_or_none()
        if meta is not None:
            meta.name = dst
            meta.updated_at = _dt.utcnow()
    elif whole and dst is None:
        await s.execute(delete(SavedReplySequence).where(SavedReplySequence.account_id == account_id,
                                                         SavedReplySequence.name == src))
    await sync_sequences(s, account_id, () if whole else {src, dst})
