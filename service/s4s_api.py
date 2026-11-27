from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

import account_health
import account_page
from db.engine import get_session
from db.models import Account, Action, S4SBlock, S4SPost, S4SProfile, UserAccount
from employees import AgencyContext
from s4s_common import _json_object, _owner_context, listed_to
from s4s_media import post_media, prune
from route_wire import own_row_or_404, wire
from s4s_requests_api import _own_ids, _primary_caption, _projection
from s4s_schedule_api import opt_out_cascade

log = logging.getLogger("of-relay.s4s_api")

router = APIRouter(prefix="/admin/s4s", tags=["s4s"])

MAX_POSTS = 20
MAX_CAPTION = 5000
MAX_DISPLAY = 64
MAX_AVATAR_URL = 2048
MAX_DISCOVERY = 200


def live_posting() -> bool:
    import runtime_switches
    # Read on every call, never captured at import (like ALLOW_ANONYMOUS_ADMIN); a sealed relay (CHATTERLY_TEST_MODE) runs no executor, so it posts nothing whatever this reads.
    return runtime_switches.on("S4S_LIVE_POSTING")




def _default_name(account: Account) -> str:
    # Never the account id: these fields reach other Agencies through Discovery, and a foreign account id never appears in a response.
    return (account.nickname or "").strip()[:MAX_DISPLAY]




_of_me = account_page.of_me


def _of_hosted(url: Any) -> bool:
    from of_client import OF_CDN_SUFFIXES

    if not isinstance(url, str) or not url.startswith("https://") or len(url) > MAX_AVATAR_URL:
        return False
    host = url[len("https://"):].split("/", 1)[0].lower()
    return host.endswith(OF_CDN_SUFFIXES)


def _apply_identity(row: S4SProfile, me: dict[str, Any] | None) -> None:
    username = str((me or {}).get("username") or "").strip()[:MAX_DISPLAY]
    if username:
        thumbs = me.get("avatarThumbs") if isinstance(me.get("avatarThumbs"), dict) else {}
        avatar = thumbs.get("c144") or me.get("avatar")
        row.display_name = str(me.get("name") or "").strip()[:MAX_DISPLAY] or username
        row.username = username
        row.avatar_url = avatar if _of_hosted(avatar) else None
    elif not _of_hosted(row.avatar_url):
        row.avatar_url = None


def _post_out(p: S4SPost, media: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": p.id, "caption": p.caption, "is_primary": bool(p.is_primary), "media": media}


async def _post_with_media(s, p: S4SPost) -> dict[str, Any]:
    return _post_out(p, (await post_media(s, [p.id])).get(p.id, []))


def _default_row(account: Account) -> S4SProfile:
    name = _default_name(account)
    return S4SProfile(
        account_id=account.id, opted_in=False, discovery_visible=True, daily_limit=1,
        display_name=name, username=name, avatar_url=None,
    )


async def _fill_primary(s, account_id: str | None = None) -> None:
    orphaned = (
        select(func.min(S4SPost.id))
        .group_by(S4SPost.account_id)
        .having(func.max(S4SPost.is_primary) == 0)
    )
    if account_id is not None:
        orphaned = orphaned.where(S4SPost.account_id == account_id)
    await s.execute(
        update(S4SPost).where(S4SPost.id.in_(orphaned))
        .values(is_primary=True, updated_at=datetime.utcnow())
        .execution_options(synchronize_session=False)
    )


async def _profile_out(s, row: S4SProfile) -> dict[str, Any]:
    posts = (await s.execute(
        select(S4SPost).where(S4SPost.account_id == row.account_id).order_by(S4SPost.id)
    )).scalars().all()
    media = await post_media(s, [p.id for p in posts])
    return {
        "account_id": row.account_id,
        "profile_id": row.id,
        "opted_in": bool(row.opted_in),
        "discovery_visible": bool(row.discovery_visible),
        "daily_limit": row.daily_limit,
        "display_name": row.display_name,
        "username": row.username,
        "avatar_url": row.avatar_url,
        "posts": [_post_out(p, media.get(p.id, [])) for p in posts],
    }


@router.get("/profiles")
async def list_profiles() -> dict[str, Any]:
    """The caller's own Creators, each with its S4S Setting and S4S posts.

    ASSUMPTION: "own" is the Agency's `user_accounts` rows, the Master's
    included, so a Master lists only the Creators linked to its own user, as
    Phase 1's Agency context makes the Master its own Agency. Rung 3
    (`agency_scope.agency_account_ids`). Overturned if the Master should list
    every Creator in the Deployment.
    """
    ctx = await _owner_context()
    async with get_session() as s:
        ids = (await s.execute(
            select(Account.id)
            .join(UserAccount, UserAccount.account_id == Account.id)
            .where(UserAccount.user_id == ctx.agency_user_id)
            .order_by(func.lower(func.coalesce(Account.nickname, Account.id)), Account.id)
        )).scalars().all()
    # Read outside the session: no database transaction waits on OnlyFans; a dead session gets no OF call.
    dead = await account_health.dead_session_map()

    async def me_of(aid: str) -> dict[str, Any] | None:
        return None if aid in dead else await _of_me(aid)
    mes = await asyncio.gather(*(me_of(a) for a in ids))
    async with get_session() as s:
        await _fill_primary(s)
        accounts = {a.id: a for a in (await s.execute(select(Account).where(Account.id.in_(ids)))).scalars()}
        rows = {r.account_id: r for r in (await s.execute(
            select(S4SProfile).where(S4SProfile.account_id.in_(ids))
        )).scalars().all()}
        profiles = []
        for aid, me in zip(ids, mes):
            row = rows.get(aid) or _default_row(accounts[aid])
            _apply_identity(row, me)
            profiles.append(await _profile_out(s, row))
    return {"live_posting": live_posting(), "profiles": profiles}


def _bool(body: dict, key: str) -> bool:
    v = body[key]
    if not isinstance(v, bool):
        raise HTTPException(status_code=400, detail=f"{key} must be true or false")
    return v


_PROFILE_FIELDS = ("opted_in", "discovery_visible", "daily_limit")


def _parse_profile_body(body: dict[str, Any]) -> dict[str, Any]:
    unknown = set(body) - set(_PROFILE_FIELDS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown field(s): {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for key in ("opted_in", "discovery_visible"):
        if key in body:
            out[key] = _bool(body, key)
    if "daily_limit" in body:
        v = body["daily_limit"]
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 3:
            raise HTTPException(status_code=400, detail="daily_limit must be 1, 2 or 3")
        out["daily_limit"] = v
    return out


def _audit_profile(s, ctx: AgencyContext, row: S4SProfile, changed: list[str]) -> None:
    s.add(Action(
        employee_id=ctx.employee_id,
        account_id=row.account_id,
        action="s4s.profile_update",
        target_type="s4s_profile",
        target_id=str(row.id),
        payload_json=json.dumps({
            "agency_user_id": ctx.agency_user_id,
            "profile_id": row.id,
            "changed": changed,
            "opted_in": bool(row.opted_in),
        }),
        at=datetime.utcnow(),
    ))


# Ids are strings parsed in the handler: a typed path parameter would let FastAPI answer 422 before the 401/403 session checks run.
@router.put("/profiles/{account_id}")
async def put_profile(account_id: str, request: Request) -> dict[str, Any]:
    """Upsert the Creator's S4S Setting with the fields sent.

    A change from opted in to opted out runs the opt-out cascade in the
    save's own transaction (`s4s_schedule_api.opt_out_cascade`): the
    Creator's own pending and skipped requests and its own future slots are
    cancelled, and nothing of the other Agency is written.
    """
    ctx = await _owner_context(account_id)
    fields = _parse_profile_body(await _json_object(request))
    me = await _of_me(account_id)
    async with get_session() as s:
        account = await s.get(Account, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="creator not found")
        row = (await s.execute(
            select(S4SProfile).where(S4SProfile.account_id == account_id)
        )).scalar_one_or_none()
        now = datetime.utcnow()
        if row is None:
            row = _default_row(account)
            row.created_at = now
            s.add(row)
        was_opted_in = bool(row.opted_in)
        for key, value in fields.items():
            setattr(row, key, value)
        _apply_identity(row, me)
        if row.opted_in and not (row.display_name and row.username):
            raise HTTPException(
                status_code=400,
                detail="this Creator's OnlyFans profile could not be read, so partners would see no name; "
                       "check its connection and try again",
            )
        row.updated_at = now
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="the profile changed meanwhile; try again") from None
        _audit_profile(s, ctx, row, sorted(fields))
        if was_opted_in and not row.opted_in:
            await opt_out_cascade(s, ctx, account_id, now)
        return await _profile_out(s, row)




def _caption(body: dict[str, Any]) -> str:
    v = body.get("caption")
    if not isinstance(v, str) or not v.strip():
        raise HTTPException(status_code=400, detail="caption is required")
    if len(v) > MAX_CAPTION:
        raise HTTPException(status_code=400, detail=f"caption is over {MAX_CAPTION} characters")
    return v


@router.post("/profiles/{account_id}/posts")
async def create_post(account_id: str, request: Request) -> dict[str, Any]:
    """A new S4S post, Primary when the Creator has no Primary post.

    ASSUMPTION: create answers 200 with the post, not 201. Rung 3 (POST
    /admin/shifts answers 200). Overturned if the app needs 201.
    ASSUMPTION: a post created while the Creator has no Primary post becomes
    its Primary post; any later one does not. Rung 4: the settings page's
    "Create post" sits in the Primary post box ("This post will be used for
    all Share for Share requests"), and a Creator with posts but no Primary
    is missing from Discovery and can send no request, which owners read as
    S4S being broken. Overturned by Infloww evidence that its first post
    stays unmarked.
    """
    await _owner_context(account_id)
    caption = _caption(await _json_object(request))
    async with get_session() as s:
        n = (await s.execute(
            select(func.count()).select_from(S4SPost).where(S4SPost.account_id == account_id)
        )).scalar_one()
        if n >= MAX_POSTS:
            raise HTTPException(status_code=409, detail=f"a Creator keeps at most {MAX_POSTS} S4S posts")
        has_primary = await _primary_caption(s, account_id) is not None
        now = datetime.utcnow()
        post = S4SPost(account_id=account_id, caption=caption, is_primary=not has_primary,
                       created_at=now, updated_at=now)
        s.add(post)
        await s.flush()
        return _post_out(post, [])


@router.patch("/profiles/{account_id}/posts/{post_id}")
async def edit_post(account_id: str, post_id: str, request: Request) -> dict[str, Any]:
    await _owner_context(account_id)
    async with get_session() as s:
        post = await own_row_or_404(s, S4SPost, post_id, "post", "account_id", account_id)
        post.caption = _caption(await _json_object(request))
        post.updated_at = datetime.utcnow()
        await s.flush()
        return await _post_with_media(s, post)


@router.delete("/profiles/{account_id}/posts/{post_id}")
async def delete_post(account_id: str, post_id: str) -> dict[str, Any]:
    """Remove the post. Deleting the Primary post moves the mark to the
    oldest post left, if any. Its media detach (the foreign key's SET NULL)
    and go at once unless a live request or slot still names them."""
    await _owner_context(account_id)
    async with get_session() as s:
        post = await own_row_or_404(s, S4SPost, post_id, "post", "account_id", account_id)
        await s.delete(post)
        await s.flush()
        await _fill_primary(s, account_id)
        deleted = post.id
    await prune()
    return {"deleted": deleted}


@router.post("/profiles/{account_id}/posts/{post_id}/primary")
async def set_primary_post(account_id: str, post_id: str) -> dict[str, Any]:
    """Move the Creator's Primary mark to this post, in one transaction:
    the old mark is cleared first, so the partial unique index never sees
    two."""
    await _owner_context(account_id)
    async with get_session() as s:
        post = await own_row_or_404(s, S4SPost, post_id, "post", "account_id", account_id)
        now = datetime.utcnow()
        await s.execute(
            update(S4SPost)
            .where(S4SPost.account_id == account_id, S4SPost.is_primary.is_(True), S4SPost.id != post.id)
            .values(is_primary=False, updated_at=now)
        )
        await s.execute(update(S4SPost).where(S4SPost.id == post.id).values(is_primary=True, updated_at=now))
        await s.refresh(post)
        return await _post_with_media(s, post)




@router.get("/discover")
async def discover(q: str = "") -> list[dict[str, Any]]:
    """The S4S projection of every listed Creator in this Deployment, the
    caller's own included and flagged `own_agency`. Only these nine keys
    leave the Relay: never an account id, a vault media id, a nickname, fan
    data or notes.

    Listed means opted in, `discovery_visible`, a Primary post, and at
    least one `user_accounts` row: a Creator that left every Agency is
    absent, and so is one whose Agency was deleted, because deleting the
    `users` row cascades its `user_accounts` rows.

    ASSUMPTION: `q` is a case-insensitive substring of the display name or
    the @username, with a leading "@" dropped and LIKE wildcards matched
    literally. Rung 5 (the spec's "filter by name or @username"). Overturned
    by Infloww evidence of prefix or exact matching.
    ASSUMPTION: the sort ignores case, ties broken by profile id. Rung 3
    (`list_profiles` sorts by lower(nickname)). Overturned by an owner
    wanting case-sensitive order.
    ASSUMPTION: `own_agency` means linked to the caller's Agency user in
    `user_accounts`, so a Master owns only its own links, as in
    `list_profiles`. Rung 3. Overturned with that assumption.
    """
    ctx = await _owner_context()
    needle = q.strip().removeprefix("@").strip().lower()
    stmt = (
        select(S4SProfile, S4SPost.id, S4SPost.caption)
        .join(S4SPost, (S4SPost.account_id == S4SProfile.account_id) & S4SPost.is_primary.is_(True))
        .where(*listed_to(ctx.agency_user_id))
        .order_by(func.lower(S4SProfile.display_name), S4SProfile.id)
        .limit(MAX_DISCOVERY)
    )
    if needle:
        stmt = stmt.where(
            func.lower(S4SProfile.display_name).contains(needle, autoescape=True)
            | func.lower(S4SProfile.username).contains(needle, autoescape=True)
        )
    async with get_session() as s:
        await _fill_primary(s)
        rows = (await s.execute(stmt)).all()
        media = await post_media(s, [post_id for _, post_id, _ in rows])
        own = await _own_ids(s, ctx.agency_user_id)
    return [
        {
            "profile_id": p.id,
            "display_name": p.display_name,
            "username": p.username,
            "avatar_url": p.avatar_url,
            "primary_caption": caption,
            "primary_media": [{"id": m["id"], "media_type": m["media_type"]} for m in media.get(post_id, [])],
            "daily_limit": p.daily_limit,
            "opted_in": bool(p.opted_in),
            "own_agency": p.account_id in own,
        }
        for p, post_id, caption in rows
    ]




def _block_out(b: S4SBlock) -> dict[str, Any]:
    return {**json.loads(b.projection_json), "blocked_at": wire(b.created_at)}


@router.get("/blocks")
async def list_blocks() -> list[dict[str, Any]]:
    """The Creators the caller's Agency blocked, newest first, each as its
    S4S projection stored at block time (never a live read, ADR-0011)."""
    ctx = await _owner_context()
    async with get_session() as s:
        rows = (await s.execute(
            select(S4SBlock).where(S4SBlock.agency_user_id == ctx.agency_user_id)
            .order_by(S4SBlock.created_at.desc(), S4SBlock.id.desc())
        )).scalars().all()
        return [_block_out(b) for b in rows]


@router.post("/blocks")
async def block_creator(request: Request) -> dict[str, Any]:
    """Block a listed Creator by S4S profile id: gone from this Agency's
    Discovery, and no request either way with this Agency's Creators.

    ASSUMPTION: a block leaves already accepted slots alone (the owner
    cancels its own slot from the schedule) and refuses only new requests
    and Accepts. Rung 4 (a booked slot is the partner's too; ending it is
    each side's own call). Overturned by an owner wanting a block to cancel
    its own booked slots with the partner.
    """
    ctx = await _owner_context()
    body = await _json_object(request)
    pid = body.get("profile_id")
    if set(body) - {"profile_id"} or isinstance(pid, bool) or not isinstance(pid, int):
        raise HTTPException(status_code=400, detail="profile_id: the Creator's S4S profile id is required")
    async with get_session() as s:
        p = await s.get(S4SProfile, pid)
        caption = None if p is None else await _primary_caption(s, p.account_id)
        if p is None or not p.opted_in or not p.discovery_visible or caption is None:
            raise HTTPException(status_code=404, detail="creator not found")
        if p.account_id in await _own_ids(s, ctx.agency_user_id):
            raise HTTPException(status_code=400, detail="you cannot block your own Creator")
        await s.execute(sqlite_insert(S4SBlock).values(
            agency_user_id=ctx.agency_user_id, account_id=p.account_id,
            projection_json=json.dumps(_projection(p, caption)), created_at=datetime.utcnow(),
        ).on_conflict_do_nothing(index_elements=["agency_user_id", "account_id"]))
        row = (await s.execute(select(S4SBlock).where(
            S4SBlock.agency_user_id == ctx.agency_user_id, S4SBlock.account_id == p.account_id,
        ))).scalar_one()
        return _block_out(row)


@router.delete("/blocks/{profile_id}")
async def unblock_creator(profile_id: str) -> dict[str, Any]:
    """Lift the caller's Agency's block on this S4S profile id; 404 if none."""
    ctx = await _owner_context()
    try:
        pid = int(profile_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="block not found") from None
    async with get_session() as s:
        row = (await s.execute(
            select(S4SBlock).join(S4SProfile, S4SProfile.account_id == S4SBlock.account_id)
            .where(S4SBlock.agency_user_id == ctx.agency_user_id, S4SProfile.id == pid)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="block not found")
        await s.delete(row)
        return {"unblocked": pid}
