from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select

import automation_executor as ax
import platforms
from automation_registry import register
from db.engine import get_session
from db.models import Fan, FollowLog, FollowPingState, Message
from side_effect_gate import PLATFORM_LACKS_PREFIX
from smart_list_rules import rules_refusal
from ._knobs import bool_knob
from ._skiplist import load_hard_skip_ids

log = logging.getLogger("of-relay.automation.auto_follow")

_DEFAULT_DAILY_CAP = 50
_MAX_DAILY_CAP = 1000
_DEFAULT_RECENT_DAYS = 7
_DEFAULT_PING_GAP_DAYS = 14
_HEADROOM_FACTOR = 5
_NOTIFY_OUTCOMES = ("followed", "refollowed", "pinged")
_EXAMINED_OUTCOMES = ("already_following", "paid_profile", "no_price")
_EXPIRED_REFUSAL = f"{PLATFORM_LACKS_PREFIX}recent_expired_subscribers"


def _headroom(cap: int) -> int:
    return max(cap, 1) * _HEADROOM_FACTOR


def _int_knob(payload: dict, key: str, default: int, *, lo: int, hi: int | None = None,
              zero_default: bool = False) -> int:
    raw = payload.get(key)
    try:
        v = default if raw is None else int(raw)
    except (TypeError, ValueError):
        v = default
    if zero_default and v <= 0:
        v = default
    if hi is not None:
        v = min(v, hi)
    return max(lo, v)



async def _recent_active_fan_ids(account_id: str, days: int, limit: int) -> list[int]:
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.created_at)
            .where(Message.account_id == str(account_id),
                   Message.direction == "in",
                   Message.is_unsent.is_(False),
                   Message.created_at >= cutoff)
            .order_by(Message.created_at.desc())
        )).all()
    seen: set[int] = set()
    out: list[int] = []
    for fid, _ in rows:
        fid = int(fid)
        if fid in seen:
            continue
        seen.add(fid)
        out.append(fid)
        if len(out) >= limit:
            break
    return out


def _all_stored_pool_q(account_id: str, *, exclude: set[int] | None = None,
                       examined_before: datetime | None = None):
    q = select(Fan.fan_id).where(Fan.account_id == str(account_id))
    if exclude:
        q = q.where(Fan.fan_id.not_in([int(f) for f in exclude]))
    if examined_before is not None:
        q = q.where(or_(Fan.follow_examined_at.is_(None),
                        Fan.follow_examined_at < examined_before))
    return q


async def _all_stored_fan_ids(account_id: str, limit: int,
                              exclude: set[int] | None = None,
                              examined_before: datetime | None = None) -> list[int]:
    q = (_all_stored_pool_q(account_id, exclude=exclude,
                            examined_before=examined_before)
         .order_by(Fan.last_message_received_at.desc().nullslast(),
                   Fan.fan_id.desc())
         .limit(limit))
    async with get_session() as s:
        rows = (await s.execute(q)).all()
    return [int(r[0]) for r in rows]


async def _all_stored_eligible_count(account_id: str,
                                    exclude: set[int] | None = None,
                                    examined_before: datetime | None = None) -> int:
    q = select(func.count()).select_from(
        _all_stored_pool_q(account_id, exclude=exclude,
                           examined_before=examined_before).subquery())
    async with get_session() as s:
        return int((await s.execute(q)).scalar() or 0)


async def _recent_expired_fan_ids(client) -> list[int]:
    res = await asyncio.to_thread(client.recent_expired_subscribers)
    rows = res.get("list") if isinstance(res, dict) else res
    out: list[int] = []
    for u in rows if isinstance(rows, list) else []:
        try:
            out.append(int(u["id"] if isinstance(u, dict) else u))
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def _owned_rules(smart_list_id, account_id: str) -> dict | None:
    from smart_lists_api import _rules_of, live_row
    try:
        sid = int(smart_list_id)
    except (TypeError, ValueError):
        log.warning("auto_follow smart_list=%r is not an id — ignoring", smart_list_id)
        return None
    async with get_session() as s:
        row = await live_row(s, sid)
        if row is None:
            return None
        if str(row.account_id) != str(account_id):
            log.warning("auto_follow smart_list=%s belongs to account=%s, not %s — ignoring",
                        sid, row.account_id, account_id)
            return None
        return _rules_of(row)


async def _resolve_smart_list(smart_list_id, account_id: str) -> list[int]:
    from smart_lists_api import _load_normalised_fans, resolve
    rules = await _owned_rules(smart_list_id, account_id)
    if rules is None:
        return []
    fans = await _load_normalised_fans(account_id, rules)
    return resolve(rules, fans)


async def _resolve_targets(account_id: str, targets: dict, cap: int) -> list[int]:
    targets = targets or {}
    source = str(targets.get("source") or "recent_active")
    if source == "fan_ids":
        raw = targets.get("fan_ids") or []
        return [int(x) for x in raw if str(x).lstrip("-").isdigit()][:cap]
    if source == "smart_list":
        sid = targets.get("smart_list_id")
        if sid is None:
            return []
        return (await _resolve_smart_list(sid, account_id))[:cap]
    days = int(targets.get("days") or _DEFAULT_RECENT_DAYS)
    return await _recent_active_fan_ids(account_id, days, cap)


def _source_list(targets: dict) -> list[str]:
    raw = (targets or {}).get("source") or "all_stored"
    names = raw if isinstance(raw, (list, tuple)) else [raw]
    out: list[str] = []
    for n in names:
        n = str(n).strip()
        if n and n not in out:
            out.append(n)
    return out or ["all_stored"]


async def _merge_pools(account_id: str, client, sources: list[str],
                       targets: dict, headroom: int,
                       exclude: set[int] | None = None,
                       examined_before: datetime | None = None) -> list[int]:
    exclude = exclude or set()
    seen: set[int] = set()
    pool: list[int] = []
    for name in sources:
        # Explicit fan_ids bypass the cooldown filter as an operator override.
        skip = set() if name == "fan_ids" else exclude
        try:
            if name == "expired":
                ids = await _recent_expired_fan_ids(client)
            elif name == "all_stored":
                ids = await _all_stored_fan_ids(account_id, headroom,
                                                exclude=exclude,
                                                examined_before=examined_before)
            else:
                ids = await _resolve_targets(account_id, {**targets, "source": name},
                                             headroom)
        except Exception:
            if name == "all_stored":
                log.error("auto_follow source=all_stored FAILED account=%s — the "
                          "backfill query is broken, not an unreachable pool",
                          account_id, exc_info=True)
                raise
            log.warning("auto_follow source=%s failed account=%s — skipping it",
                        name, account_id, exc_info=True)
            continue
        for fid in ids:
            if fid not in seen and fid not in skip:
                seen.add(fid)
                pool.append(fid)
        if len(pool) >= headroom:
            break
    return pool



class _StrandedError(RuntimeError):
    pass


def _classify(u: dict, *, unfollow_first: bool) -> str:
    price = u.get("subscribePrice")
    # bool is an int subclass: subscribePrice false would read as free (0) and get charged.
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return "no_price"
    if float(price) != 0:
        return "paid_profile"
    if u.get("subscribedBy"):
        return "pinged" if unfollow_first else "already_following"
    if u.get("subscribedByExpireDate"):
        return "refollowed"
    return "followed"


def follow_is_free(account_id: str) -> bool:
    return platforms.for_account(str(account_id)).free_follow


async def gated_follow(client, fan_id: int, *, account_id: str,
                       unfollow_first: bool = False,
                       money_gate: bool = True) -> str:
    if not money_gate or follow_is_free(account_id):
        await asyncio.to_thread(client.follow_user, fan_id)
        return "followed"
    u = await asyncio.to_thread(client.get_user, fan_id)
    u = u if isinstance(u, dict) else {}
    outcome = _classify(u, unfollow_first=unfollow_first)
    if outcome in ("no_price", "paid_profile", "already_following"):
        return outcome
    if outcome == "pinged":
        await asyncio.to_thread(client.unfollow_user, fan_id)
        try:
            await asyncio.to_thread(client.follow_user, fan_id)
        except Exception:
            try:
                await asyncio.to_thread(client.resubscribe_user, fan_id)
            except Exception as e:
                raise _StrandedError(str(e)) from e
        return "pinged"
    if outcome == "refollowed":
        try:
            await asyncio.to_thread(client.resubscribe_user, fan_id)
        except Exception:
            await asyncio.to_thread(client.follow_user, fan_id)
        return "refollowed"
    await asyncio.to_thread(client.follow_user, fan_id)
    return "followed"


def _notified(counts: Counter) -> int:
    return sum(counts[o] for o in _NOTIFY_OUTCOMES)


async def _follow_batch(
    account_id: str, client, pool: list[int], cap: int, *, unfollow_first: bool,
    money_gate: bool = True,
) -> tuple[Counter, int, int]:
    counts: Counter = Counter()
    stranded = errors = 0
    label = "ping" if unfollow_first else "follow"
    for fid in pool:
        if _notified(counts) >= cap:
            break
        try:
            outcome = await gated_follow(client, fid, account_id=account_id,
                                          unfollow_first=unfollow_first,
                                          money_gate=money_gate)
            counts[outcome] += 1
            if outcome in _NOTIFY_OUTCOMES:
                await stamp_ping(account_id, fid)
            elif outcome in _EXAMINED_OUTCOMES:
                await _stamp_examined(account_id, fid)
        except _StrandedError:
            stranded += 1
            log.error("auto_follow %s STRANDED account=%s fan=%s — unfollowed "
                      "but re-follow failed", label, account_id, fid, exc_info=True)
        except Exception:
            errors += 1
            log.warning("auto_follow %s failed account=%s fan=%s",
                        label, account_id, fid, exc_info=True)
    return counts, stranded, errors


async def _client_or_none(account_id: str):
    try:
        return await asyncio.to_thread(ax._make_client, account_id)
    except Exception:
        log.warning("auto_follow preview: no OF client for account=%s", account_id,
                    exc_info=True)
        return None


async def _preview_batch(
    client, pool: list[int], cap: int, *, account_id: str, unfollow_first: bool,
) -> tuple[Counter, list[int], int]:
    counts: Counter = Counter()
    would: list[int] = []
    errors = 0
    if follow_is_free(account_id):
        would = list(pool[:max(cap, 0)])
        counts["followed"] = len(would)
        return counts, would, errors
    for fid in pool[:max(cap, 0)]:
        try:
            u = await asyncio.to_thread(client.get_user, fid)
        except Exception:
            errors += 1
            log.warning("auto_follow preview get_user failed fan=%s", fid, exc_info=True)
            continue
        outcome = _classify(u if isinstance(u, dict) else {},
                            unfollow_first=unfollow_first)
        counts[outcome] += 1
        if outcome in _NOTIFY_OUTCOMES:
            would.append(fid)
    return counts, would, errors


def _pool_exhausted(pool: list[int], counts: Counter, errors: int,
                    *, examined: int | None = None) -> bool:
    if not pool or errors:
        return False
    if examined is not None and examined < len(pool):
        return False
    return _notified(counts) == 0


def _verdict_counts(counts: Counter) -> dict:
    return {
        "already_following": counts["already_following"],
        "paid_profile_skipped": counts["paid_profile"],
        "no_price_skipped": counts["no_price"],
    }


def _preview_result(pool: list[int], cap: int, counts: Counter,
                    errors: int) -> dict:
    examined = min(len(pool), max(cap, 0))
    return {
        "candidates": len(pool),
        "examined": examined,
        **_verdict_counts(counts),
        "pool_exhausted": _pool_exhausted(pool, counts, errors,
                                          examined=examined),
        "errors": errors,
        "cap": cap,
    }



async def _recently_pinged_ids(account_id: str, gap_days: int) -> set[int]:
    cutoff = datetime.utcnow() - timedelta(days=max(1, gap_days))
    async with get_session() as s:
        rows = (await s.execute(
            select(FollowPingState.fan_id)
            .where(FollowPingState.account_id == str(account_id),
                   FollowPingState.last_pinged_at >= cutoff)
        )).all()
    return {int(r[0]) for r in rows}


async def stamp_ping(account_id: str, fan_id: int) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        row = await s.get(FollowPingState, (str(account_id), int(fan_id)))
        if row is None:
            s.add(FollowPingState(account_id=str(account_id), fan_id=int(fan_id),
                                  last_pinged_at=now, ping_count=1))
        else:
            row.last_pinged_at = now
            row.ping_count = (row.ping_count or 0) + 1
        s.add(FollowLog(account_id=str(account_id), fan_id=int(fan_id), followed_at=now))


async def _stamp_examined(account_id: str, fan_id: int) -> None:
    async with get_session() as s:
        row = await s.get(Fan, (str(account_id), int(fan_id)))
        if row is not None:
            row.follow_examined_at = datetime.utcnow()



def select_follow_pool(merged: list[int], *, hard_skip: set[int],
                       headroom: int) -> list[int]:
    return [f for f in merged if f not in hard_skip][:headroom]


async def _source_refusal(account_id: str, sources: list[str], targets: dict) -> str | None:
    if "expired" in sources and platforms.refusal_for_account(str(account_id), "recent_expired_subscribers"):
        return _EXPIRED_REFUSAL
    if "smart_list" not in sources or targets.get("smart_list_id") is None:
        return None
    rules = await _owned_rules(targets["smart_list_id"], account_id)
    return None if rules is None else rules_refusal(platforms.for_account(str(account_id)), rules)


def _refused(dry_run: bool, sources: list[str], reason: str) -> dict:
    return {"action": "follow", "dry_run": dry_run, "source": ",".join(sources),
            "status": "skipped", "reason": reason, "candidates": 0}


async def _run_follow(account_id: str, payload: dict, *, cap: int, dry_run: bool,
                      targets: dict, hard_skip: set) -> dict:
    sources = _source_list(targets)
    if reason := await _source_refusal(account_id, sources, targets):
        return _refused(dry_run, sources, reason)
    client = (await _client_or_none(account_id) if dry_run
              else await asyncio.to_thread(ax._make_client, account_id))
    if client is None:
        return {"action": "follow", "dry_run": True, "candidates": 0,
                "skipped": "of_unreachable"}
    # bool_knob, not bool(payload.get(k, True)): a stored null would resolve to gate OFF and buy priced profiles.
    money_gate = bool_knob(payload, "money_gate", True)
    headroom = _headroom(cap)
    # hi=365: SQLite raises past 32766 bound params, and a huge gap would bind the whole ledger.
    gap_days = _int_knob(payload, "min_days_between_pings", _DEFAULT_PING_GAP_DAYS,
                         lo=1, hi=365, zero_default=True)
    recently = await _recently_pinged_ids(account_id, gap_days)
    examined_before = datetime.utcnow() - timedelta(days=gap_days)
    pool = await _merge_pools(account_id, client, sources, targets, headroom,
                              exclude=recently,
                              examined_before=examined_before)
    source = ",".join(sources)
    pool = select_follow_pool(pool, hard_skip=hard_skip, headroom=headroom)

    eligible = (await _all_stored_eligible_count(
        account_id, exclude=recently | hard_skip, examined_before=examined_before)
        if sources == ["all_stored"] else None)

    if dry_run:
        if not money_gate:
            would = pool[:max(cap, 0)]
            return {"action": "follow", "dry_run": True, "source": source,
                    "money_gate": False, "would_follow": would,
                    "candidates": len(pool), "examined": len(would),
                    **({"eligible": eligible} if eligible is not None else {}),
                    "unpriced_follows": len(would), "cap": cap,
                    "warning": "money_gate off — paid profiles WILL be charged"}
        counts, would, errors = await _preview_batch(client, pool, cap,
                                                     account_id=account_id,
                                                     unfollow_first=False)
        return {"action": "follow", "dry_run": True, "source": source,
                "would_follow": would,
                **({"eligible": eligible} if eligible is not None else {}),
                **_preview_result(pool, cap, counts, errors)}

    counts, _, errors = await _follow_batch(account_id, client, pool, cap,
                                            unfollow_first=False,
                                            money_gate=money_gate)
    pool_exhausted = _pool_exhausted(pool, counts, errors)
    return {"action": "follow", "dry_run": False, "source": source,
            "money_gate": money_gate,
            "candidates": len(pool), "followed": counts["followed"],
            "refollowed": counts["refollowed"],
            **_verdict_counts(counts),
            "pool_exhausted": pool_exhausted,
            **({"eligible": eligible} if eligible is not None else {}),
            "errors": errors, "cap": cap}


_ACTIONS = {
    "follow": _run_follow,
}


@register("auto_follow")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    action = payload.get("action")
    # Unknown action skips; never default to follow, which can buy a priced profile.
    runner = _ACTIONS.get(action) if isinstance(action, str) else None
    if runner is None:
        log.warning("auto_follow account=%s: action %r is not 'follow' — skipped",
                    account_id, action)
        return {"skipped": "bad_action", "action": action}
    return await runner(
        account_id, payload,
        cap=_int_knob(payload, "daily_cap", _DEFAULT_DAILY_CAP, lo=0, hi=_MAX_DAILY_CAP),
        dry_run=bool_knob(payload, "dry_run", True),
        targets=payload.get("targets") or {},
        hard_skip=await load_hard_skip_ids(account_id),
    )
