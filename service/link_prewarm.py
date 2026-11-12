"""service/link_prewarm.py — the hourly pre-warm of the Growth links' figures
(link_metrics: trial links and promotions; of_tracking_api: tracking links).

`prewarm_all` (server.py; each account about every PREWARM_EVERY_S) makes the
pages' list reads for every account with a live session, one account at a time,
the starts spread over half an hour. It re-reads a link's claimers only when its
count moved (tracking links too) and honours the OF failure back-off; its
worst-case OF call budget is on `_prewarm`. A Creator with a person's read in the
last of_pacing.USER_WINDOW_S (10 s) is skipped this pass and walked the next.

Under LINK_PREWARM_SCOPE=list_sync (the default) a pass serves list sync only: a
Creator with no List (no trial or tracking link with one, promotion List off) gets
no OF call, and on the others only links with a List are walked or marked checked,
so a display-only link's page still refreshes it on open (link_metrics.maybe_refresh)
and the Growth page refetches hourly while viewed (app/hooks/useGrowth.ts
GROWTH_VIEWED_REFRESH_MS).

Env knobs (read at call time, through `prewarm_scope()`):
  LINK_PREWARM_SCOPE=list_sync   the hourly prewarm walks only Creators with a List and only
                                 their links with one (docs/spec/phase-03-smaller-cuts.md);
                                 all = every Creator and link (the old behaviour)
"""
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

PREWARM_EVERY_S = _STALE_S          # each account's cycle: a page opens on figures under an hour old
_PREWARM_SPREAD_S = PREWARM_EVERY_S / 2   # the accounts' passes start spread over this, jittered
# server.py's loop sleeps this after a pass, which itself spends about
# _PREWARM_SPREAD_S staggering, so each account comes round about every PREWARM_EVERY_S.
PREWARM_PAUSE_S = PREWARM_EVERY_S - _PREWARM_SPREAD_S

_PREWARM_SKIPPED: set[str] = set()   # accounts prewarm_all skipped last pass (user active)

_SCOPES = ("list_sync", "all")


def prewarm_scope() -> str:
    """Knob LINK_PREWARM_SCOPE, read now: `list_sync` (default) or `all`. Anything
    else warns and gives the default."""
    raw = (os.environ.get("LINK_PREWARM_SCOPE") or "").strip().lower()
    if not raw:
        return _SCOPES[0]
    if raw not in _SCOPES:
        log.warning("link_prewarm_bad_env name=LINK_PREWARM_SCOPE value=%r — using default %s", raw, _SCOPES[0])
        return _SCOPES[0]
    return raw


ListLinks = dict[str, "set[int] | None"]   # kind -> OF ids a pass walks (None: every one)
_ALL: ListLinks = {"trial": None, "campaign": None, "promo": None}


async def list_links(account_id: str) -> ListLinks:
    """The account's links with a List, per kind: trial and campaign LinkMeta rows
    with a list_id; promotions all (None) while the account's promotion List is on,
    none while it is off (a promotion's list_id only follows that setting, and
    sync_lists adds no promotion while it is off)."""
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
    """The pass reads the kind's OF list: every link (None) or some to sync."""
    return lists[kind] is None or bool(lists[kind])


def _only(lists: ListLinks, kind: str, links: list[Link]) -> list[Link]:
    return links if lists[kind] is None else [l for l in links if l[0] in lists[kind]]


async def prewarm(account_id: str) -> None:
    """`_prewarm` as a background walk (of_pacing): OF's pages for the account at
    its shared per-Creator pace, OF's 429 retried once. Under LINK_PREWARM_SCOPE
    list_sync, a Creator with no List gets no OF call (its Growth pages refresh
    when opened and hourly while viewed)."""
    lists = await list_links(account_id) if prewarm_scope() == "list_sync" else dict(_ALL)
    if not any(_kind_due(lists, k) for k in lists):
        log.info("link_prewarm_skip account=%s reason=no_list_sync", account_id)
        return
    await of_pacing.walk(account_id, "link_prewarm", lambda: _prewarm(account_id, lists))


async def _prewarm(account_id: str, lists: ListLinks) -> None:
    """Read one account's link figures ahead of any page, by the page's rules:
    the same per-account walk lock, pacing and OF failure back-off, and a link's
    claimers are re-read only when OF's count for it moved.

    OF calls per account per pass, worst case (the list reads always run):
      tracking  ceil(links / 100) /campaigns pages, plus every claimer page
                (50 a page) of each link whose countSubscribers moved
      trial     ceil(links / 100) /trials pages (at most 10), plus every
                claimer page (20 a page, up to 5 past the count) of each moved link
      promo     ceil(promos / 100) /promotions pages (at most 12), the same
      lists     one add-to-list per link with a List whose count grew
    An hour in which no count moved costs the three list reads (one page each
    up to 100 links). A kind backed off by a recent OF failure is skipped; a
    list OF does not answer, or a failed trial walk, ends the pass, and a
    tracking link OF failed on is not retried for _CLAIMERS_FAIL_TTL.

    `lists` (`list_links` under list_sync): a kind with no link to sync is not
    read, and only its links with a List are walked or marked checked; under
    `all` every kind and link (None each)."""
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


async def prewarm_all() -> None:
    """Every OnlyFans account with a session, one at a time, their starts spread
    over _PREWARM_SPREAD_S with jitter (no burst of every account at once, and
    no shared minute OF could line the accounts up by). An account whose
    session is marked dead is skipped: its OF reads could only fail. So is a
    deactivated Creator: it gets no OF call.

    A Creator with a person's read in the last of_pacing.USER_WINDOW_S (10 s)
    is skipped in its turn (one `bg_walk_skip` line) and walked next pass: no
    waiting, so a pass never runs late. Skipped once, it is walked next pass even
    if still busy (a Creator always in use is never starved). The pacer alone keeps
    the walks off OF's limit; this only keeps a pass's burst off a person's own reads."""
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
