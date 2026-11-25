from __future__ import annotations

import asyncio
import logging
import os
import random

from sqlalchemy import select

import accounts as account_registry
from account_health import dead_session_map, is_deactivated
from db.engine import get_session
from db.models import LinkMeta, PromoCampaign, PromoListSetting
import of_pacing
import of_tracking_api
from of_promos import fetch_of_promos, fetch_of_trials
from link_metrics import (Link, _STALE_S, _backed_off, links_of_promos, links_of_trials, past_promo_ids,
                          refresh)

log = logging.getLogger("of-relay.link_prewarm")

PREWARM_EVERY_S = _STALE_S
_PREWARM_SPREAD_S = PREWARM_EVERY_S / 2
# The loop sleeps this after a pass that already spends ~_PREWARM_SPREAD_S staggering.
PREWARM_PAUSE_S = PREWARM_EVERY_S - _PREWARM_SPREAD_S

_PREWARM_SKIPPED: set[str] = set()

_SCOPES = ("list_sync", "all")


def prewarm_scope() -> str:
    raw = (os.environ.get("LINK_PREWARM_SCOPE") or "").strip().lower()
    if not raw:
        return _SCOPES[0]
    if raw not in _SCOPES:
        log.warning("link_prewarm_bad_env name=LINK_PREWARM_SCOPE value=%r — using default %s", raw, _SCOPES[0])
        return _SCOPES[0]
    return raw


ListLinks = dict[str, "set[int] | None"]
_ALL: ListLinks = {"trial": None, "campaign": None, "promo": None}


async def list_links(account_id: str) -> ListLinks:
    async with get_session() as s:
        rows = (await s.execute(select(LinkMeta.kind, LinkMeta.of_id).where(
            LinkMeta.account_id == account_id, LinkMeta.kind.in_(("trial", "campaign")),
            LinkMeta.list_id.is_not(None)))).all()
        st = await s.get(PromoListSetting, account_id)
    out: ListLinks = {"trial": set(), "campaign": set(),
                      "promo": None if st is not None and st.enabled and st.list_id else set()}
    for kind, of_id in rows:
        out[kind].add(of_id)
    return out


def _kind_due(lists: ListLinks, kind: str) -> bool:
    return lists[kind] is None or bool(lists[kind])


def _only(lists: ListLinks, kind: str, links: list[Link]) -> list[Link]:
    return links if lists[kind] is None else [l for l in links if l[0] in lists[kind]]


async def prewarm(account_id: str) -> None:
    lists = await list_links(account_id) if prewarm_scope() == "list_sync" else dict(_ALL)
    if not any(_kind_due(lists, k) for k in lists):
        log.info("link_prewarm_skip account=%s reason=no_list_sync", account_id)
        return
    await of_pacing.walk(account_id, "link_prewarm", lambda: _prewarm(account_id, lists))


async def _prewarm(account_id: str, lists: ListLinks) -> None:
    if _kind_due(lists, "campaign") and not await of_tracking_api.prewarm(account_id, lists["campaign"]):
        return
    if not _backed_off(account_id, "trial") and _kind_due(lists, "trial"):
        trials = await fetch_of_trials(account_id)
        if trials is None:
            return
        await refresh(account_id, "trial", _only(lists, "trial", links_of_trials(trials)))
        if _backed_off(account_id, "trial"):
            return
    if not _backed_off(account_id, "promo") and _kind_due(lists, "promo"):
        promos = await fetch_of_promos(account_id)
        if promos is None:
            return
        async with get_session() as s:
            mirrors = (await s.execute(select(PromoCampaign).where(
                PromoCampaign.account_id == account_id))).scalars().all()
        await refresh(account_id, "promo", _only(lists, "promo", links_of_promos(
            promos, mirrors, await past_promo_ids(account_id))))


# A busy Creator is skipped once, then walked next pass even if still busy (never starved).
async def prewarm_all() -> None:
    live = [m["id"] for m in account_registry.list_accounts()
            if m.get("has_session") and m.get("platform") == "onlyfans"]
    gap = _PREWARM_SPREAD_S / max(len(live), 1)
    for i, aid in enumerate(live):
        if i:
            await asyncio.sleep(gap * random.uniform(0.5, 1.5))
        if aid not in _PREWARM_SKIPPED and of_pacing.user_active(aid):
            _PREWARM_SKIPPED.add(aid)
            log.info("bg_walk_skip account=%s kind=link_prewarm", aid)
            continue
        _PREWARM_SKIPPED.discard(aid)
        await _prewarm_live(aid)


async def _prewarm_live(aid: str) -> None:
    if aid in await dead_session_map() or await is_deactivated(aid):
        return
    try:
        await prewarm(aid)
    except Exception:
        log.info("link_prewarm failed account=%s", aid, exc_info=True)
