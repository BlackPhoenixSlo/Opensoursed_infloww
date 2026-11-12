"""service/of_promos.py — shared OnlyFans promo helpers.

Used by BOTH `promotions_api` (the Growth → Promotion surface) and
`automations/promo_reactivate` (the re-arm automation), so the OF contract lives
in exactly one place. Deliberately free of FastAPI imports so the automation
plugin scan stays light. The /trials fetch lives here too (`fetch_of_trials`):
trial_links_api and link_metrics' pre-warm both read it, and link_metrics
cannot import trial_links_api (which imports link_metrics).

The contract below was captured LIVE (2026-07-22, Ava):
  • GET  /promotions  → {"hasMore": bool, "items": [ {...}, ... ]}   (NOT "list")
  • POST /promotions  → a LIST containing the created promo: [ {...} ]
  • create requires `discount` — an INTEGER PERCENT in [1, 100]; `price` is not
    a valid field.
  • an item carries: id, message, price, type, claimsCount, subscribeCounts,
    subscribeDays, createdAt, finishedAt, isFinished, canClaim.
    There is NO `discount` on read — the mirror row is the only record of it.
  • `isFinished` is NOT a reliable liveness flag: OF leaves it False on spent
    promos indefinitely (9 of Ava's 304, oldest 2025-12, all canClaim=False).
    A promo is on offer only when isFinished is false AND canClaim isn't false.
  • GET /promotions is PAGED (10 by default, limit honoured to 100+) and its
    `hasMore` is ALWAYS true — stop on a short page, never on hasMore.
  • deleting a promo does not remove it from /promotions; OF flips it to
    isFinished=true / canClaim=false and keeps it in history.

A history longer than the page cap is read in full at most once per
PROMO_HISTORY_REREAD_S (`fetch_of_promos`' memo, docs/spec/phase-03-smaller-cuts.md).

Env knobs (read at call time, through `promo_history_reread_s()`):
  PROMO_HISTORY_REREAD_S=86400   inside it, a capped account's reads page only to the
                                 promotions that can still change (the rest from the
                                 memo); 0 = a full read every call (the old behaviour)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from sqlalchemy import select

import automation_executor as ax
from db.engine import get_session
from db.models import PromoCampaign, PromoListSetting
from of_coerce import cents_or_zero

log = logging.getLogger("of-relay.of_promos")


def of_field(item: dict, *names, default=None):
    """First present key among `names` (OF field spellings drift)."""
    for n in names:
        if n in item and item[n] is not None:
            return item[n]
    return default


def safe_int(v, default: int = 0) -> int:
    """Tolerant int coercion — OF drift ('30.0', dicts, None) must NEVER 500."""
    try:
        if isinstance(v, bool):
            return int(v)
        return int(float(v))
    except (TypeError, ValueError):
        return default


def coerce_of_id(v) -> int | None:
    """OF entry id → int, or None when it isn't numeric (drift-safe)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


to_cents = cents_or_zero


def normalise_of_promo(item: dict) -> dict:
    """One OF promo entry → our flat shape (coercion never raises).

    Liveness needs BOTH `isFinished` and `canClaim`. OF does not reliably flip
    isFinished on a spent promo: 9 of Ava's 304 promos carry isFinished=False
    with canClaim=False, the oldest from 2025-12 — dead for months. Reading
    isFinished alone showed them as live campaigns in the UI, and would have
    made promo_reactivate stand down forever ("a promo is already live") on an
    account that actually has no offer running.
    """
    finished = bool(of_field(item, "isFinished", default=False))
    can_claim = item.get("canClaim")
    # Absent canClaim → don't infer death from it; only an explicit False counts.
    is_live = (not finished) and (can_claim is not False)
    return {
        "of_promo_id": coerce_of_id(of_field(item, "id", "promoId")),
        "price_cents": to_cents(of_field(item, "price", default=0)),
        "subscribe_counts": safe_int(of_field(item, "subscribeCounts", "subscribe_counts", default=0)),
        "subscribe_days": safe_int(of_field(item, "subscribeDays", "subscribe_days", default=0)),
        "message": of_field(item, "message", "text", default=""),
        "promo_type": of_field(item, "type", default="all"),
        "created_at": of_field(item, "createdAt"),
        # performance = how many claimed it
        "subscriber_count": safe_int(of_field(item, "claimsCount", "countSubscribers",
                                              "subscribersCount", default=0)),
        "can_claim": can_claim,
        # "finished" here means "not on offer", which is what every caller
        # actually wants to know.
        "is_finished": not is_live,
        "status": "active" if is_live else "finished",
    }


# A promo's audience: OF's "all" (new subscribers), "expired", or both. OF's own
# Start campaign (ModalPromotion saveForm) sends `type` as a list; a single
# audience still goes as the bare string the live-verified create used. The
# mirror stores one String column, so both is kept as "all,expired".
PROMO_AUDIENCES = ("all", "expired")


def promo_type_store(value) -> str:
    """Create-body `type` (a string or OF's list) -> the mirror's promo_type.
    Raises ValueError on anything but "all" / "expired" (or both)."""
    given = {value} if isinstance(value, str) else set(value or [])
    if not given or not given <= set(PROMO_AUDIENCES):
        raise ValueError('type: "all" and/or "expired"')
    return ",".join(v for v in PROMO_AUDIENCES if v in given)


def promo_type_body(stored: str | None):
    """The mirror's promo_type -> OF's create `type`: "all" / "expired" as the
    string, both as OF's list ["all", "expired"]."""
    vals = [v for v in (stored or "all").split(",") if v in PROMO_AUDIENCES] or ["all"]
    return vals[0] if len(vals) == 1 else vals


def extract_created_promo(res) -> dict:
    """OF's create returns a LIST holding the created promo; some shapes wrap it
    as {"items":[...]} or return the bare object. Pull the created item out so
    the caller can capture of_promo_id — without it, delete/re-arm can't reach
    OF and a live promo is orphaned."""
    if isinstance(res, list) and res and isinstance(res[0], dict):
        return res[0]
    if isinstance(res, dict):
        items = res.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        return res
    return {}


def _rows_from_payload(raw, keys: tuple[str, ...]) -> list | None:
    """The item list out of an OF list response, or None if the shape is unusable
    (caller treats None as 'OF not reachable'). `keys` are the dict spellings to try
    in order — OF list bodies wrap the rows under different keys per endpoint
    (/promotions → "items", /trials → "list")."""
    if isinstance(raw, dict):
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v if isinstance(v, list) else None
        return None
    return raw if isinstance(raw, list) else None


_PAGE = 100
_MAX_PAGES = 12          # 1200 promos — a hard backstop, see below

# Why paged_of_fetch stopped (PagedRows.stop).
STOP_END = "end"         # a short page: the real end of history
STOP_NEED = "need_ids"   # every id the caller asked about was seen
STOP_CAP = "cap"         # max_pages read, OF still had more: history truncated


class PagedRows(list):
    """paged_of_fetch's rows (a plain list to every caller) and why paging stopped."""
    stop: str = STOP_END


async def paged_of_fetch(
    account_id: str,
    *,
    page_call,
    normalise,
    id_key: str,
    payload_keys: tuple[str, ...] = ("items", "list"),
    max_pages: int = _MAX_PAGES,
    need_ids: set[int] | None = None,
    label: str = "of",
) -> PagedRows | None:
    """Best-effort live OF fetch of a PAGED list endpoint. Returns the (possibly
    empty) normalised list on success, or None when the fetch failed (no session /
    OF error) — callers use None-vs-list to tell 'not reachable' apart from
    'reachable, zero rows'. The list's `stop` says why paging ended (STOP_*).

    OF list endpoints paginate and their `hasMore` flag is unreliable (it can stay
    true past the real end), so we stop on a short/empty page, with `max_pages` as a
    hard backstop. Dedupe is by `id_key`. `need_ids` is an early exit: once every id
    the caller cares about has been seen we stop paging.

      page_call(client, offset, limit) -> raw OF response
      normalise(dict)                  -> flat dict carrying its id under `id_key`
      payload_keys                     -> dict spellings the rows live under, in order
    """
    try:
        client = await asyncio.to_thread(ax._make_client, account_id)
    except Exception:
        log.info("%s OF client failed account=%s — mirror-only", label, account_id, exc_info=True)
        return None

    out = PagedRows()
    seen: set[int] = set()
    outstanding = set(need_ids or ())
    for page in range(max_pages):
        try:
            raw = await asyncio.to_thread(page_call, client, page * _PAGE, _PAGE)
        except Exception:
            # A mid-page failure means we hold a PARTIAL history. Returning it
            # would look like "these rows no longer exist" to the caller, so
            # report unreachable instead and let it fail closed.
            log.info("%s OF fetch failed account=%s page=%s — mirror-only",
                     label, account_id, page, exc_info=True)
            return None
        rows = _rows_from_payload(raw, payload_keys)
        if rows is None:
            return None
        for x in rows:
            if not isinstance(x, dict):
                continue
            item = normalise(x)
            rid = item.get(id_key)
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
                outstanding.discard(rid)
            out.append(item)
        if len(rows) < _PAGE:
            out.stop = STOP_END        # short page = end of history
            break
        if need_ids is not None and not outstanding:
            out.stop = STOP_NEED       # found everything the caller asked about
            break
    else:
        out.stop = STOP_CAP
        log.warning("%s paging hit the %s-page cap account=%s — history truncated",
                    label, max_pages, account_id)
    return out


_REREAD_DEFAULT_S = 86_400.0


def promo_history_reread_s() -> float:
    """Knob PROMO_HISTORY_REREAD_S, read now: the capped-history memo's window in
    seconds (0 = off). A malformed or negative value warns and gives the default."""
    raw = os.environ.get("PROMO_HISTORY_REREAD_S")
    if raw is None or not raw.strip():
        return _REREAD_DEFAULT_S
    try:
        v = float(raw)
    except ValueError:
        v = -1.0
    if v < 0:
        log.warning("promo_bad_env name=PROMO_HISTORY_REREAD_S value=%r — using default %s",
                    raw, _REREAD_DEFAULT_S)
        return _REREAD_DEFAULT_S
    return v


# account -> (monotonic time of its last capped read, that read's rows as merged by
# the reads since, the account's mirrored of_promo_ids as of that read). In-process:
# a restart costs one full read.
_MEMO: dict[str, tuple[float, list[dict], frozenset[int]]] = {}


async def _promo_list_sync_on(account_id: str) -> bool:
    """The account's promotion List is on (link_metrics.sync_lists' rule)."""
    async with get_session() as s:
        st = await s.get(PromoListSetting, account_id)
    return st is not None and bool(st.enabled) and bool(st.list_id)


async def _mirror_promo_ids(account_id: str) -> set[int]:
    async with get_session() as s:
        return {int(o) for o in (await s.execute(select(PromoCampaign.of_promo_id).where(
            PromoCampaign.account_id == account_id,
            PromoCampaign.of_promo_id.is_not(None)))).scalars()}


async def fetch_of_promos(
    account_id: str,
    *,
    need_ids: set[int] | None = None,
    max_pages: int = _MAX_PAGES,
) -> list[dict] | None:
    """Best-effort live OF fetch of /promotions, PAGED, over paged_of_fetch (the
    shared skeleton /trials uses too).

    /promotions' `hasMore` is useless — it stayed true past offset 180 on a
    230-promo history — so paging stops on a short page. `need_ids` is an early
    exit: promo_reactivate only needs to locate its own armed campaigns, so it
    costs one request instead of two dozen. A call with `need_ids` never touches
    the memo below.

    The memo: a read with no `need_ids` that hits the page cap is kept with its
    time and the account's mirrored of_promo_ids. Inside PROMO_HISTORY_REREAD_S of
    it, on an account whose promotion List is off, a read with no `need_ids` pages
    only until it has seen the promotions that can still change (the memo's ones
    on offer, plus every mirror of_promo_id new since the memo's read: a promotion
    made or re-armed through the app shows on the next read) and returns those
    pages merged over the memo by id, fresh rows winning. A short page (the real
    end) clears the memo, a need_ids stop keeps it (its rows merged, its mirror ids
    now), a cap stop renews it with that read's rows alone (nothing pushed past the
    cap lingers); a failed read is None and leaves it. With the List on, every
    pass reads in full, so a new promotion's claimers are never enrolled late.
    """
    async def read(need: set[int] | None) -> PagedRows | None:
        return await paged_of_fetch(
            account_id,
            page_call=lambda c, off, lim: c.promotions(offset=off, limit=lim),
            normalise=normalise_of_promo,
            id_key="of_promo_id",
            payload_keys=("items", "list"),
            max_pages=max_pages,
            need_ids=need,
            label="promotions",
        )

    window = promo_history_reread_s()
    if need_ids is not None or window <= 0:
        return await read(need_ids)
    memo = _MEMO.get(account_id)
    if memo is not None and (time.monotonic() - memo[0] >= window
                             or await _promo_list_sync_on(account_id)):
        memo = None
    mirrors = frozenset(await _mirror_promo_ids(account_id))
    need = None
    if memo is not None:
        need = {r["of_promo_id"] for r in memo[1]
                if not r.get("is_finished") and r.get("of_promo_id") is not None}
        need |= mirrors - memo[2]
    rows = await read(need)
    if rows is None:
        return None
    out: list[dict] = rows
    if rows.stop == STOP_END:
        _MEMO.pop(account_id, None)
    elif rows.stop == STOP_CAP:
        _MEMO[account_id] = (time.monotonic(), out, mirrors)
    elif memo is not None:
        fresh = {r.get("of_promo_id") for r in rows}
        out = [*rows, *(r for r in memo[1] if r.get("of_promo_id") not in fresh)]
        _MEMO[account_id] = (memo[0], out, mirrors)
    return out


def normalise_of_trial(item: dict) -> dict:
    """One OF /trials entry -> our flat shape (coercion never raises).

    Field names captured LIVE (2026-07-22, Ava): an entry carries id,
    trialLinkName, url, subscribeDays, subscribeCounts, claimCounts,
    clicksCounts, createdAt, expiredAt, isFinished, sharedWith, user.
    Note there is no `name` key — the operator's label is `trialLinkName`.
    """
    finished = bool(of_field(item, "isFinished", default=False))
    return {
        "of_trial_id": coerce_of_id(of_field(item, "id", "trialId")),
        "name": of_field(item, "name", "trialLinkName", default=""),
        "url": of_field(item, "url", "shareUrl", "link"),
        "subscribe_days": safe_int(of_field(item, "subscribeDays", "subscribe_days", default=0)),
        "subscribe_counts": safe_int(of_field(item, "subscribeCounts", "subscribe_counts", default=0)),
        "claim_counts": safe_int(of_field(item, "claimCounts", "claimsCount", "usedCount", default=0)),
        # A spent/expired link keeps appearing in /trials. Without these the UI
        # rendered a dead link identically to a live one.
        "clicks_count": safe_int(of_field(item, "clicksCounts", "clickCounts", default=0)),
        "expired_at": of_field(item, "expiredAt"),
        "created_at": of_field(item, "createdAt"),
        "is_finished": finished,
        "status": "finished" if finished else "active",
    }


async def fetch_of_trials(account_id: str) -> list[dict] | None:
    """Best-effort live OF fetch of /trials, PAGED. Thin wrapper over
    paged_of_fetch (the shared skeleton /promotions uses too) — same
    None-vs-list contract: None = OF not reachable, [] = reachable, no links.

    /trials pages at THREE items by default, so an un-paged call showed 3 of
    Ava's 18 links — the operator saw a fraction of their own links and could
    not tell. limit=100 returns the lot in one request; the loop covers an
    account with more. Rows arrive under "list" (OF) with "items" as a fallback.
    """
    return await paged_of_fetch(
        account_id,
        page_call=lambda c, off, lim: c.trial_links(offset=off, limit=lim),
        normalise=normalise_of_trial,
        id_key="of_trial_id",
        payload_keys=("list", "items"),
        max_pages=10,
        label="trial_links",
    )
