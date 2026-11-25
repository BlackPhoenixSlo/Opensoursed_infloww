from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

from sqlalchemy import select

import automation_executor as ax
from db.engine import get_session
from db.models import PromoCampaign, PromoListSetting
from isotime import parse_iso
from of_coerce import cents_or_zero

log = logging.getLogger("of-relay.of_promos")


def of_field(item: dict, *names, default=None):
    for n in names:
        if n in item and item[n] is not None:
            return item[n]
    return default


def safe_int(v, default: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return int(v)
        return int(float(v))
    except (TypeError, ValueError):
        return default


def coerce_of_id(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


to_cents = cents_or_zero


def normalise_of_promo(item: dict) -> dict:
    finished = bool(of_field(item, "isFinished", default=False))
    can_claim = item.get("canClaim")
    cap = safe_int(of_field(item, "subscribeCounts", "subscribe_counts", default=0))
    raw_claims = of_field(item, "claimsCount", "countSubscribers", "subscribersCount")
    claims = safe_int(raw_claims, default=0)
    # A missing or junk count reads as 0 but is never trusted.
    claims_present = raw_claims is not None and safe_int(raw_claims, default=-1) >= 0
    capped = cap > 0 and claims >= cap
    # Absent canClaim: don't infer death; only an explicit False counts.
    flags_live = (not finished) and (can_claim is not False)
    is_live = flags_live and not capped
    return {
        "of_promo_id": coerce_of_id(of_field(item, "id", "promoId")),
        "price_cents": to_cents(of_field(item, "price", default=0)),
        "subscribe_counts": cap,
        "subscribe_days": safe_int(of_field(item, "subscribeDays", "subscribe_days", default=0)),
        "message": of_field(item, "message", "text", default=""),
        "promo_type": of_field(item, "type", default="all"),
        "created_at": of_field(item, "createdAt"),
        "finished_at": of_field(item, "finishedAt"),
        "subscriber_count": claims,
        "claims_present": claims_present,
        "can_claim": can_claim,
        "is_finished": not is_live,
        # Ended only by our claims >= cap reading while OF's flags still say live: re-create needs a trusted claim history.
        "cap_inferred": flags_live and capped,
        "status": "active" if is_live else "finished",
    }


def promo_expires_at(finished_at, finish_days: int | None, created: datetime) -> datetime | None:
    of = parse_iso(finished_at)
    if of is not None and of > created:
        return of
    if finish_days and int(finish_days) > 0:
        return created + timedelta(days=int(finish_days))
    return None


PROMO_AUDIENCES = ("all", "expired")


def promo_type_store(value) -> str:
    given = {value} if isinstance(value, str) else set(value or [])
    if not given or not given <= set(PROMO_AUDIENCES):
        raise ValueError('type: "all" and/or "expired"')
    return ",".join(v for v in PROMO_AUDIENCES if v in given)


def promo_type_body(stored: str | None):
    vals = [v for v in (stored or "all").split(",") if v in PROMO_AUDIENCES] or ["all"]
    return vals[0] if len(vals) == 1 else vals


def extract_created_promo(res) -> dict:
    if isinstance(res, list) and res and isinstance(res[0], dict):
        return res[0]
    if isinstance(res, dict):
        items = res.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        return res if of_field(res, "id", "promoId") is not None else {}
    return {}


def _rows_from_payload(raw, keys: tuple[str, ...]) -> list | None:
    if isinstance(raw, dict):
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v if isinstance(v, list) else None
        return None
    return raw if isinstance(raw, list) else None


_PAGE = 100
_MAX_PAGES = 12

STOP_END = "end"
STOP_NEED = "need_ids"
STOP_CAP = "cap"


class PagedRows(list):
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
    raise_dead: bool = False,
    on_error=None,
) -> PagedRows | None:
    def dead(e: Exception) -> bool:
        import account_health
        if raise_dead and account_health.is_session_dead_error(e) is not None:
            return True
        if on_error is not None:
            on_error(e)
        return False

    try:
        client = await asyncio.to_thread(ax._make_client, account_id)
    except Exception as e:
        if dead(e):
            raise
        log.info("%s OF client failed account=%s — mirror-only", label, account_id, exc_info=True)
        return None

    out = PagedRows()
    seen: set[int] = set()
    outstanding = set(need_ids or ())
    for page in range(max_pages):
        try:
            raw = await asyncio.to_thread(page_call, client, page * _PAGE, _PAGE)
        except Exception as e:
            if dead(e):
                raise
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
            out.stop = STOP_END
            break
        if need_ids is not None and not outstanding:
            out.stop = STOP_NEED
            break
    else:
        out.stop = STOP_CAP
        log.warning("%s paging hit the %s-page cap account=%s — history truncated",
                    label, max_pages, account_id)
    return out


_REREAD_DEFAULT_S = 86_400.0


def promo_history_reread_s() -> float:
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


_MEMO: dict[str, tuple[float, list[dict], frozenset[int]]] = {}


async def _promo_list_sync_on(account_id: str) -> bool:
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
    raise_dead: bool = False,
    on_error=None,
) -> list[dict] | None:
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
            raise_dead=raise_dead,
            on_error=on_error,
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
    finished = bool(of_field(item, "isFinished", default=False))
    return {
        "of_trial_id": coerce_of_id(of_field(item, "id", "trialId")),
        "name": of_field(item, "name", "trialLinkName", default=""),
        "url": of_field(item, "url", "shareUrl", "link"),
        "subscribe_days": safe_int(of_field(item, "subscribeDays", "subscribe_days", default=0)),
        "subscribe_counts": safe_int(of_field(item, "subscribeCounts", "subscribe_counts", default=0)),
        "claim_counts": safe_int(of_field(item, "claimCounts", "claimsCount", "usedCount", default=0)),
        "clicks_count": safe_int(of_field(item, "clicksCounts", "clickCounts", default=0)),
        "expired_at": of_field(item, "expiredAt"),
        "created_at": of_field(item, "createdAt"),
        "is_finished": finished,
        "status": "finished" if finished else "active",
    }


async def fetch_of_trials(account_id: str) -> list[dict] | None:
    return await paged_of_fetch(
        account_id,
        page_call=lambda c, off, lim: c.trial_links(offset=off, limit=lim),
        normalise=normalise_of_trial,
        id_key="of_trial_id",
        payload_keys=("list", "items"),
        max_pages=10,
        label="trial_links",
    )
