"""service/trial_links_api.py — Free-trial link generator (Growth surface).

Mint / label / delete OnlyFans free-trial links and read their redemptions. OF
is the source of truth (of_client.trial_links / create_trial_link /
delete_trial_link); we keep a light `trial_link_mirrors` row per link so the
operator's name survives and the table renders even when a live OF fetch is
unavailable.

Routes (owner-gated, under /admin/*):
  GET    /admin/trial-links?account_id=   merged mirror ∪ live OF (best-effort)
  POST   /admin/trial-links               create on OF + upsert mirror; Source, Promo cost,
                                          Tag and List (of_tracking_api._MetaFields) are stored
                                          for the new id (link_metrics.store_meta), meta_saved
  DELETE /admin/trial-links/{mirror_id}   delete on OF + drop mirror row

The GET's OF refresh is best-effort: if the account has no live session (or OF
errors) the endpoint still returns the mirror rows, so the page never hard-fails
on a read.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import Field
from sqlalchemy import select

import automation_executor as ax
import link_metrics
import link_share_api
from api_errors import raise_if_free_page_denied
from auth import assert_account_owned
from db.engine import get_session
from db.models import TrialLinkMirror
from of_mirror import delete_mirrored, merge_mirrors
from of_promos import fetch_of_trials, normalise_of_trial, safe_int
from of_tracking_api import _MetaFields

log = logging.getLogger("of-relay.trial_links_api")

router = APIRouter()


@router.get("/admin/trial-links")
async def list_trial_links(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    async with get_session() as s:
        mirrors = (await s.execute(
            select(TrialLinkMirror).where(TrialLinkMirror.account_id == account_id)
            .order_by(TrialLinkMirror.created_at.desc())
        )).scalars().all()

    fetched = await fetch_of_trials(account_id)

    # Mirror rows carry the operator's name; live OF carries the usage counters.
    def _from_mirror(m: TrialLinkMirror, live: dict | None) -> dict:
        return {
            "id": m.id,
            "of_trial_id": m.of_trial_id,
            "name": m.name,
            "url": (live or {}).get("url") or m.url,
            "subscribe_days": (live or {}).get("subscribe_days") or m.subscribe_days,
            "subscribe_counts": (live or {}).get("subscribe_counts") or m.subscribe_counts,
            "claim_counts": (live or {}).get("claim_counts", m.claim_counts),
            "clicks_count": (live or {}).get("clicks_count"),
            "expired_at": (live or {}).get("expired_at"),
            # Only OF knows whether a link is spent. With no live row to read
            # (OF down, or the link no longer listed) say so rather than
            # implying it's live — /trials ordering is unstable, so "absent"
            # is not proof of "finished".
            "status": (live or {}).get("status", "unknown"),
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "source": "mirror",
        }

    # OF links that have no mirror row (created outside Inflowwww) — read-only.
    def _from_live(t: dict) -> dict:
        return {
            "id": None,
            "of_trial_id": t["of_trial_id"],
            "name": t["name"],
            "url": t["url"],
            "subscribe_days": t["subscribe_days"],
            "subscribe_counts": t["subscribe_counts"],
            "claim_counts": t["claim_counts"],
            "clicks_count": t["clicks_count"],
            "expired_at": t["expired_at"],
            "status": t["status"],
            "created_at": t.get("created_at"),
            "source": "onlyfans",
        }

    out = merge_mirrors(mirrors, fetched, of_id_attr="of_trial_id",
                        live_id_key="of_trial_id",
                        from_mirror=_from_mirror, from_live=_from_live)
    # Infloww's per-link figures (cached claimers x ledger, refreshed in the
    # background past an hour, re-walking only links whose claimCounts moved)
    # and the Edit dialog's Promo cost / Source / Tag.
    figures = await link_metrics.for_list(
        account_id, "trial",
        {r["of_trial_id"]: [r["of_trial_id"]] for r in out if r.get("of_trial_id")},
        None if fetched is None else link_metrics.links_of_trials(fetched))
    meta, sources, tags = await link_metrics.meta_for(account_id, "trial")
    for r in out:
        r["metrics"] = figures["by"].get(r.get("of_trial_id"), dict(link_metrics._UNWALKED))
        r.update(meta.get(r.get("of_trial_id")) or link_metrics.meta_fields(None))
    # Share links on these links take the read just made (never fails the read); with OF
    # not reachable the mirror rows have no counts, so a report keeps its last read.
    if fetched is not None:
        await link_share_api.refresh_shares(account_id, "trial", {r["of_trial_id"]: r for r in out if r.get("of_trial_id")})
    # None = the OF fetch failed (not reachable); [] = reachable but no links.
    return {"links": out, "of_available": fetched is not None,
            "metrics_updated_at": figures["updated_at"], "metrics_refreshing": figures["refreshing"],
            "sources": sources, "tags": tags}


class _CreateBody(_MetaFields):
    account_id: str
    name: str
    subscribe_days: int = 7
    subscribe_counts: int = 1
    expired_at: str | None = None
    # Offer expiration: the link's validity in days, 0 = no expiration (OF's
    # `expireDays`, which Infloww's and OF's own Create link send). None = not sent.
    expire_days: int | None = Field(None, ge=0, le=30)


@router.post("/admin/trial-links")
async def create_trial_link(body: _CreateBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    # OF rejects subscribeDays < 1 outright ("SubscribeDays must be at least 1"),
    # so 0 is invalid here, NOT "unlimited". subscribeCounts=0 IS accepted and
    # means unlimited claims. Both verified live 2026-07-23 on Ava.
    days = max(1, min(int(body.subscribe_days), 365))
    counts = max(0, min(int(body.subscribe_counts), 100000))
    meta = link_metrics.clean_meta(body)   # a bad field is refused before OF creates anything

    try:
        # _make_client is inside the try so a missing/expired session surfaces
        # as a clean 502 (with a reason) rather than an unhandled 500.
        client = await asyncio.to_thread(ax._make_client, body.account_id)
        res = await asyncio.to_thread(
            lambda: client.create_trial_link(
                name=name, subscribe_days=days,
                subscribe_counts=counts, expired_at=body.expired_at,
                **({} if body.expire_days is None else {"expire_days": int(body.expire_days)})),
        )
    except Exception as e:
        log.warning("create_trial_link OF call failed account=%s", body.account_id, exc_info=True)
        raise_if_free_page_denied(e, "trial links")
        raise HTTPException(502, f"OnlyFans trial link create failed (session/API): {repr(e)[:200]}")

    of = normalise_of_trial(res if isinstance(res, dict) else {})
    now = datetime.utcnow()
    async with get_session() as s:
        row = TrialLinkMirror(
            account_id=body.account_id,
            of_trial_id=of.get("of_trial_id"),
            name=name, subscribe_days=days, subscribe_counts=counts,
            url=of.get("url"), claim_counts=of.get("claim_counts") or 0,
            created_at=now,
        )
        s.add(row)
        await s.flush()
        mirror_id = row.id
    out: dict[str, Any] = {
        "id": mirror_id, "of_trial_id": of.get("of_trial_id"), "name": name,
        "url": of.get("url"), "subscribe_days": days, "subscribe_counts": counts,
        "claim_counts": of.get("claim_counts") or 0,
        "clicks_count": of.get("clicks_count") or 0,
        "expired_at": of.get("expired_at"), "status": "active",
        "source": "mirror", **link_metrics.meta_fields(None), "meta_saved": True}
    wanted = meta["promo_cost_cents"] is not None or meta["source"] or meta["tags"] or meta["list_id"]
    if wanted:
        tid = safe_int(of.get("of_trial_id"))
        if tid:
            # A new link has no claimers: count 0 is "added", so the List's first add runs
            # once one claims (refresh() -> sync_lists).
            out.update(await link_metrics.store_meta(body.account_id, "trial", tid, meta, claim_count=0))
        else:
            out["meta_saved"] = False   # OF's reply had no id: created, the fields could not be kept
    log.info("trial_link_created id=%s account=%s of_id=%s meta_saved=%s", mirror_id, body.account_id,
             of.get("of_trial_id"), out["meta_saved"])
    return out


@router.delete("/admin/trial-links/{mirror_id}")
async def delete_trial_link(mirror_id: int) -> dict[str, Any]:
    return await delete_mirrored(
        TrialLinkMirror, mirror_id, of_id_attr="of_trial_id",
        of_delete=lambda c, oid: c.delete_trial_link(oid),
        not_found="trial link not found", label="trial_link")
