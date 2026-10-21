"""service/link_share_api.py — Infloww's Share links: a public, read-only
report on some of one Creator's free trial links or tracking links, for
someone outside the agency (Infloww's third "Share links" tab: name, links,
"Include earnings"; viewable for 7 days, then expired).

The URL is /share/<id>.<secret> (the Next page app/app/share/[token]); its data
is GET /share/<id>.<secret>/data here, outside the share-token gate
(server._PUBLIC_PREFIXES). The id is not secret; the secret is
secrets.token_urlsafe(24), compared in constant time. Unknown or wrong: 404.
Revoked or past expires_at: 410.

What the public sees is `rows_json`, one row per picked link: its name, date
created and OF's counts (a free trial link's claims and clicks; a tracking
link's clicks and subscribers), and, with "Include earnings", the link's net
Earnings, Fans who spent and fans counted, as the list shows them. Never a fan
(no names, ids or per-fan spend), never the account id, the link URL, the
Promo cost, Source or Tag.

The public request does nothing but read that row: no OnlyFans call, no
ledger read, so it costs one primary-key lookup and needs no rate limit. The
rows are built only from the owner's own reads of the links (the free trial
links list, the tracking links earnings), which call `refresh_shares`: create
stores the share with every row pending (Infloww's "may take up to 30
minutes"), the page reads the links again at once and that read fills them;
each later read rebuilds them, so a report is as fresh as the last time
someone opened the page. A link not in a read keeps its last row (a link never
read is left out of the report); a read with OnlyFans down rebuilds nothing.
That matches the house's no-scheduler rule (link_metrics' List adds).

Owner-only: a chatter session is refused (403), and every route checks the
account is the caller's.

Routes:
  GET    /admin/link-shares?account_id=&kind=trial|campaign   the shares not revoked
  POST   /admin/link-shares   {account_id, kind, name, of_ids, include_earnings}
  DELETE /admin/link-shares/{share_id}?account_id=   revoke (the report answers 410)
  GET    /share/{key}/data   public: the report
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from auth import assert_account_owned
from chatters import assert_owner, current_actor
from db.engine import get_session
from db.models import LinkShare
from of_promos import safe_int

log = logging.getLogger("of-relay.link_share_api")

router = APIRouter()

KINDS = ("trial", "campaign")
TTL = timedelta(days=7)        # Infloww: "Once ready, the link can be viewed for the next 7 days"
MAX_ACTIVE = 50                # Infloww's share-limit, per agency; ours per Creator
MAX_LINKS = 100                # Infloww's links per share link


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _refuse_chatter() -> None:
    """Share links are the owner's: a chatter session is refused; the anonymous
    admin hatch is left to `assert_account_owned`."""
    if current_actor() is not None:
        assert_owner()


# ── The public rows ───────────────────────────────────────────────────

def _text(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def _count(v: Any) -> int | None:
    return None if v is None else safe_int(v)


def public_row(kind: str, r: dict, include_earnings: bool) -> dict[str, Any]:
    """One link as the public sees it, from a row of the owner's read (a free
    trial links list row, or a tracking link's campaign with its figures).
    Whitelisted: nothing else of the row can reach the report."""
    out: dict[str, Any] = {"name": _text(r.get("name")) or "", "created_at": _text(r.get("created_at"))}
    if kind == "trial":
        out.update(claims=_count(r.get("claim_counts")), clicks=_count(r.get("clicks_count")))
        fig = r.get("metrics") or {}
    else:
        out.update(clicks=_count(r.get("clicks")), subscribers=_count(r.get("subscribers")))
        fig = r
    if include_earnings:
        out.update(earnings_cents=_count(fig.get("earnings_net_cents")),
                   fans_who_spent=_count(fig.get("fans_who_spent")),
                   fans_counted=_count(fig.get("fans_counted")))
    return out


async def refresh_shares(account_id: str, kind: str, rows: dict[int, dict]) -> None:
    """Rebuild the rows of the account's live share links of `kind` from an
    owner read just made (`rows` by OF id). A link missing from it keeps its
    last row (null while never read). Never raises: the owner's read must not
    fail on a share."""
    try:
        now = _now()
        async with get_session() as s:
            shares = (await s.execute(select(LinkShare).where(
                LinkShare.account_id == account_id, LinkShare.kind == kind,
                LinkShare.revoked_at.is_(None), LinkShare.expires_at > now))).scalars().all()
            for sh in shares:
                ids = json.loads(sh.of_ids_json)
                old = json.loads(sh.rows_json)
                if not any(o in rows for o in ids):
                    continue    # none of its links in this read: nothing rebuilt, not "updated"
                sh.rows_json = json.dumps([public_row(kind, rows[o], sh.include_earnings) if o in rows else prev
                                           for o, prev in zip(ids, old)])
                sh.snapshot_at = now
    except Exception:
        log.warning("link share refresh failed account=%s kind=%s", account_id, kind, exc_info=True)


# ── Owner routes ──────────────────────────────────────────────────────

def _status(row: LinkShare, now: datetime) -> str:
    if row.expires_at <= now:
        return "expired"
    return "active" if row.snapshot_at is not None else "preparing"


def _out(row: LinkShare, now: datetime) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "kind": row.kind, "path": f"/share/{row.id}.{row.secret}",
            "of_ids": json.loads(row.of_ids_json), "include_earnings": bool(row.include_earnings),
            "created_at": _iso(row.created_at), "expires_at": _iso(row.expires_at),
            "updated_at": _iso(row.snapshot_at), "status": _status(row, now)}


@router.get("/admin/link-shares")
async def list_link_shares(account_id: str = Query(...),
                           kind: str = Query(..., pattern="^(trial|campaign)$")) -> dict[str, Any]:
    """The Creator's share links of the kind, newest first; expired ones too
    (status "expired"), revoked ones not."""
    assert_account_owned(account_id)
    _refuse_chatter()
    now = _now()
    async with get_session() as s:
        rows = (await s.execute(select(LinkShare).where(
            LinkShare.account_id == account_id, LinkShare.kind == kind, LinkShare.revoked_at.is_(None))
            .order_by(LinkShare.created_at.desc(), LinkShare.id.desc()))).scalars().all()
    return {"shares": [_out(r, now) for r in rows], "limit": MAX_ACTIVE}


class _CreateBody(BaseModel):
    account_id: str
    kind: str = Field(..., pattern="^(trial|campaign)$")
    name: str = Field(..., max_length=100)
    of_ids: list[int] = Field(..., min_length=1, max_length=MAX_LINKS)
    include_earnings: bool = False


@router.post("/admin/link-shares")
async def create_link_share(body: _CreateBody = Body(...)) -> dict[str, Any]:
    """A share link on the picked links, viewable for 7 days. Its rows are
    pending until the owner's next read of the links (the page makes it at once)."""
    assert_account_owned(body.account_id)
    _refuse_chatter()
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "This is a required field")
    ids = list(dict.fromkeys(body.of_ids))
    if any(i < 1 for i in ids):
        raise HTTPException(422, "of_ids: OnlyFans link ids")
    now = _now()
    async with get_session() as s:
        live = (await s.execute(select(func.count()).select_from(LinkShare).where(
            LinkShare.account_id == body.account_id, LinkShare.revoked_at.is_(None),
            LinkShare.expires_at > now))).scalar_one()
    if live >= MAX_ACTIVE:
        raise HTTPException(422, f"At most {MAX_ACTIVE} share links at a time. Delete one first")
    actor = current_actor()
    async with get_session() as s:
        row = LinkShare(
            secret=secrets.token_urlsafe(24), account_id=body.account_id, kind=body.kind, name=name,
            of_ids_json=json.dumps(ids), include_earnings=body.include_earnings,
            rows_json=json.dumps([None] * len(ids)), snapshot_at=None,
            created_by=actor.id if actor is not None else None,
            created_at=now, expires_at=now + TTL)
        s.add(row)
        await s.flush()
        out = _out(row, now)
    log.info("link share created account=%s kind=%s id=%s links=%s earnings=%s", body.account_id, body.kind,
             out["id"], len(ids), body.include_earnings)
    return out


@router.delete("/admin/link-shares/{share_id}")
async def revoke_link_share(share_id: int, account_id: str = Query(...)) -> dict[str, Any]:
    """Revoke: the report answers 410 from now on, and the share leaves the list."""
    assert_account_owned(account_id)
    _refuse_chatter()
    async with get_session() as s:
        row = await s.get(LinkShare, share_id)
        if row is None or row.account_id != account_id or row.revoked_at is not None:
            raise HTTPException(404, "share link not found")
        row.revoked_at = _now()
    log.info("link share revoked account=%s id=%s", account_id, share_id)
    return {"revoked": share_id}


# ── Public ────────────────────────────────────────────────────────────

@router.get("/share/{key}/data")
async def share_data(key: str, response: Response) -> dict[str, Any]:
    """The report behind a share link, for anyone holding the URL: 404 unless
    the id and secret match, 410 once revoked or expired. `ready` false: no
    read of the links has filled it yet."""
    sid, _, secret = key.partition(".")
    if not (sid.isascii() and sid.isdigit()) or len(sid) > 12 or not secret or len(secret) > 64:
        raise HTTPException(404, "Not found")
    async with get_session() as s:
        row = await s.get(LinkShare, int(sid))
    if row is None or not secrets.compare_digest(row.secret.encode(), secret.encode()):
        raise HTTPException(404, "Not found")
    if row.revoked_at is not None or row.expires_at <= _now():
        raise HTTPException(410, "This share link has expired")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    return {"name": row.name, "kind": row.kind, "include_earnings": bool(row.include_earnings),
            "updated_at": _iso(row.snapshot_at), "expires_at": _iso(row.expires_at),
            "ready": row.snapshot_at is not None, "links": [r for r in json.loads(row.rows_json) if r]}
