"""service/saved_replies_api.py — server.py's saved-replies block, moved
wholesale: local-DB saved replies (Growth > Scripts) CRUD plus tag/sequence relabel.

  GET/POST    /admin/saved-replies
  PUT/DELETE  /admin/saved-replies/{reply_id}
  POST        /admin/saved-replies/relabel

Import/copy (`/admin/saved-replies/import*`, `/copy`) live in scripts_import_api.py.
Included mid-file in server.py for route order (pinned by
service/tests/test_route_order.py).
"""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from auth import assert_account_owned

router = APIRouter()


# ── Saved replies (local-only "templates" minus welcome) ──────────────
# OF's /messages/templates rejects creates for everything except the
# welcome slot. We keep regular saved replies in the local DB and let
# the UI merge them with OF's welcome at render time.

class _SavedReplyBody(BaseModel):
    title: str | None = None
    text: str
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
    notes: str | None = Field(None, max_length=256)


_SCRIPT_TAG_MAX = 32


def _clean_tags(tags: list[str]) -> list[str]:
    """Trimmed, de-duplicated (first spelling wins), empty names dropped; 400 over 32 characters."""
    out: list[str] = []
    for t in tags:
        name = str(t).strip()
        if not name or name in out:
            continue
        if len(name) > _SCRIPT_TAG_MAX:
            raise HTTPException(status_code=400, detail=f"tag name over {_SCRIPT_TAG_MAX} characters")
        out.append(name)
    return out


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
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/admin/saved-replies")
async def admin_saved_replies_list(account_id: str = Query(...)) -> dict[str, Any]:
    """Saved replies for one account. Sorted newest-edit first.

    Each row also carries `removed_media_ids`: its media our vault mirror has
    since marked deleted on OF (`vault_items.removed_at`), so the composer can
    warn before a chatter sends a script whose media is gone."""
    assert_account_owned(account_id)
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
        media_ids = {i for ids in ids_by_row for i in ids}
        removed: set[int] = set()
        if media_ids:
            removed = set((await s.execute(
                select(VaultItem.media_id).where(
                    VaultItem.account_id == account_id,
                    VaultItem.media_id.in_(media_ids),
                    VaultItem.removed_at.is_not(None),
                ),
            )).scalars().all())
        for r, ids in zip(out, ids_by_row):
            r["removed_media_ids"] = [i for i in ids if i in removed]
        return {"list": out}


@router.post("/admin/saved-replies")
async def admin_saved_replies_create(
    body: _SavedReplyBody = Body(...),
    account_id: str = Query(...),
) -> dict[str, Any]:
    """Create a new saved reply for an account."""
    assert_account_owned(account_id)
    from db.engine import get_session
    from db.models import SavedReply
    async with get_session() as s:
        row = SavedReply(
            account_id=account_id,
            title=body.title,
            text=body.text,
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
        )
        s.add(row)
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
        row.title = body.title
        row.text = body.text
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
        row.updated_at = _dt.utcnow()
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
        await s.commit()
        return {"ok": True}


class _SavedReplyRelabelBody(BaseModel):
    """One tag or sequence edit across an account's scripts (Growth > Scripts).

    - tag, from X, to Y: rename X to Y (merging into Y if it exists); to null deletes X from every script.
    - tag, from null, to Y, ids: add Y to those scripts (the selection bar's "Add to tag").
    - sequence, from X, to Y: rename the sequence (409 if Y is another sequence's name); to null ungroups its
      scripts (script_id and script_step cleared; the scripts themselves stay).
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
    if body.kind == "tag" and dst is not None and len(dst) > _SCRIPT_TAG_MAX:
        raise HTTPException(status_code=400, detail=f"tag name over {_SCRIPT_TAG_MAX} characters")
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
        await s.commit()
        return {"updated": updated}
