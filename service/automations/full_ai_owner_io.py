from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select

import job_queue
import runtime_switches
from audience_include import audience_allows_fan
from automations import _funnel_walkers
from automations import _human_outbound
from automations import full_ai_config
from automations._skiplist import HARD_SKIP_REASONS, should_skip_muted_creator
from automations.full_ai_owner import OwnerFacts, claims, fan_after, in_fans, of_app_human, yield_left_s
from db.engine import get_session
from db.models import AccountAiConfig, Blacklist, Fan, FunnelState, MassRun, Message, SkipList

log = logging.getLogger(__name__)

KIND = "full_ai_chat"
OFF_SWITCH = "FULL_AI_CHAT_OFF"
AUDIENCE_KIND = "full_ai_live"
HARD_REASONS: frozenset[str] = frozenset(HARD_SKIP_REASONS | {"unreachable"})


async def _live(account_id: str) -> bool:
    # lazy: full_ai_live imports this module
    from automations import full_ai_live
    return await full_ai_live.live_rule(account_id) is not None


def global_off() -> str | None:
    return "off_global" if runtime_switches.on(OFF_SWITCH) else None


async def _off(account_id: str, s) -> str | None:
    if (off := global_off()) is not None:
        return off
    if await job_queue.enabled_rule_id(account_id, KIND, session=s) is None:
        return "off_rule"
    if not await _live(account_id):
        return "off_mode"
    return None


async def off_reason(account_id: str) -> str | None:
    async with get_session() as s:
        return await _off(account_id, s)


async def _checkpoint(account_id: str, s) -> dict | None:
    row = await s.get(AccountAiConfig, str(account_id))
    got = full_ai_config.loaded(row.full_ai_config_json if row is not None else None)
    if got is None:
        log.warning("full_ai_owner bad config json account=%s: nobody listed", account_id)
        return None
    return got["checkpoint"]


def _top_spend_cents(cfg: dict | None) -> int:
    v = (cfg or {}).get("top_spend_cents")
    if type(v) is int and v >= 0:
        return v
    return full_ai_config.DEFAULTS["top_spend_cents"]


_short_warned: dict[tuple[str, tuple[int, ...]], float] = {}


def _short(account_id: str, list_ids, p) -> bool:
    if p is None or p.members is None or not p.partial:
        return False
    key, at = (str(account_id), tuple(sorted({int(x) for x in list_ids}))), time.monotonic() - (p.read_age_s or 0.0)
    if abs(_short_warned.get(key, float("-inf")) - at) > 1.0:
        _short_warned[key] = at
        log.warning("full_ai_owner exclude list read short (paging backstop) account=%s lists=%s: Full AI "
                    "claims no Fan on this account until a full read", account_id, list(key[1]))
    return True


async def _members(account_id: str, client, list_ids: list[int], *, whole: bool = False) -> frozenset | None:
    from automations import autoreply
    ids = tuple(sorted(set(list_ids)))
    got = await autoreply._folder_members(account_id, client, ids)
    if got is not None and whole and _short(account_id, ids, autoreply.peek_folder(account_id, ids)):
        return None
    return got


async def _listed(account_id: str, fan_ids: set[int], cfg: dict | None, client=None) -> set[int]:
    """The Fans of `fan_ids` on the Fans list (`in_fans`). Both lists empty: everyone, no OF client
    built, no OF call. An unreadable config (`cfg` None), a malformed stored list, a client that will not
    build, a failed read or a short read of the exclusion list: the Fans on it are not listed (never widen)."""
    fans = (cfg or {}).get("fans")
    if full_ai_config._fans_error(fans) is not None:
        log.warning("full_ai_owner bad fans config account=%s", account_id)
        return set()
    inc, exc = fans["include"], fans["exclude"]
    if not inc and not exc:
        return set(fan_ids)
    on_inc = on_exc = None
    try:
        if client is None:
            import automation_executor as ax
            client = await asyncio.to_thread(ax._make_client, account_id)
        on_inc = await _members(account_id, client, inc) if inc else frozenset()
        on_exc = await _members(account_id, client, exc, whole=True) if exc else frozenset()
    except Exception:
        log.warning("full_ai_owner fans list read failed account=%s", account_id, exc_info=True)
    return {f for f in fan_ids
            if in_fans(fans, None if on_inc is None else f in on_inc, None if on_exc is None else f in on_exc)}


class FansRead(NamedTuple):
    listed: bool | None
    age_s: float | None
    failed_age_s: float | None
    fresh: bool


def cached_listed(account_id: str, fan_id: int, cfg: dict) -> FansRead:
    """`_listed` for one Fan from Auto-reply's folder cache ONLY (`autoreply.peek_folder`): no client, no
    OF call, ever. A failed newest read = not listed THEN, as `_listed` treated it; same `in_fans`."""
    from automations import autoreply   # lazy: autoreply imports this module inside its run
    fans = cfg.get("fans")
    if full_ai_config._fans_error(fans) is not None:
        return FansRead(False, None, None, True)
    ttl = autoreply._FOLDER_TTL_S
    on: list[bool | None] = []
    ages: list[float] = []
    failed: list[float] = []
    unknown = False
    for whole, ids in ((False, fans["include"]), (True, fans["exclude"])):
        p = autoreply.peek_folder(account_id, ids) if ids else None
        if whole and _short(account_id, ids, p):
            p = p._replace(members=None)
        if p is not None and p.failed_age_s is not None:
            failed.append(p.failed_age_s)
        elif p is not None and p.members is None:
            unknown = True
        elif p is not None:
            ages.append(p.read_age_s)
            on.append(int(fan_id) in p.members)
            continue
        on.append(None)
    age = max(ages) if ages else None
    if failed:
        return FansRead(in_fans(fans, on[0], on[1]), age, min(failed), False)
    if unknown:
        return FansRead(None, None, None, False)
    return FansRead(in_fans(fans, on[0], on[1]), age, None, age is None or age < ttl)


async def _hard_skip(account_id: str, fan_id: int, fan, s) -> bool:
    if should_skip_muted_creator(fan):
        return True
    if await s.get(Blacklist, int(fan_id)) is not None:
        return True
    row = (await s.execute(select(SkipList.fan_id).where(
        SkipList.account_id == str(account_id), SkipList.fan_id == int(fan_id),
        SkipList.reason.in_(tuple(HARD_REASONS))).limit(1))).first()
    return row is not None


async def _walk_advancing(account_id: str, fan_id: int, s) -> bool:
    rows = (await s.execute(
        select(FunnelState.last_error, MassRun.automation_kind)
        .join(MassRun, MassRun.id == FunnelState.mass_run_id)
        .where(MassRun.account_id == str(account_id), FunnelState.fan_id == int(fan_id),
               FunnelState.status == "pending"))).all()
    for last_error, run_kind in rows:
        if _funnel_walkers.is_hold(last_error):
            continue
        walker = _funnel_walkers.walker_for(run_kind)
        if await job_queue.enabled_rule_id(account_id, walker, session=s) is not None:
            return True
    return False


async def _human(account_id: str, fan_id: int, anchor_at: datetime, client,
                 live_read: bool, ours=frozenset()) -> tuple[str | None, datetime | None, dict | None]:
    if await _human_outbound.manual_outbound_since(account_id, fan_id, since=anchor_at):
        return "human", None, None
    if not live_read or client is None:
        return None, None, None
    try:
        data = await asyncio.to_thread(lambda: client.get_messages(fan_id, limit=10, peek=True))
        items = data.get("list") if isinstance(data, dict) else data
        items = [m for m in items or [] if isinstance(m, dict)]
        ids = {int(m["id"]) for m in items if isinstance(m.get("id"), (int, str)) and str(m["id"]).isdigit()}
        known: set[int] = set()
        if ids:
            async with get_session() as s:
                known = set((await s.execute(select(Message.message_id).where(
                    Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                    Message.message_id.in_(ids)))).scalars())
        at = of_app_human(items, fan_id=int(fan_id), anchor_at=anchor_at, known_ids=known | set(ours))
        his = fan_after(items, fan_id=int(fan_id), anchor_at=anchor_at)
    except Exception:
        log.warning("full_ai_owner OF-app read failed account=%s fan=%s", account_id, fan_id, exc_info=True)
        return None, None, None
    return ("human_of_app" if at is not None else None), at, his


async def start_human_yield(account_id: str, fan_id: int, sent_at: datetime) -> None:
    import attribution
    import fan_lease
    now = datetime.utcnow()
    left = yield_left_s(sent_at, now, await attribution._manual_yield_seconds(account_id))
    if left <= 0:
        return
    async with get_session() as s:
        until = (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).scalar_one_or_none()
    if until is not None and until >= now + timedelta(seconds=left):
        return
    await fan_lease.start_fan_cooldown(account_id, fan_id, cooldown_s=left)


async def load(account_id: str, fan_id: int, anchor_at: datetime, *, client=None,
               live_read: bool = False, ours: frozenset[int] | set[int] = frozenset(),
               cached: bool = False) -> OwnerFacts:
    async with get_session() as s:
        off = await _off(account_id, s)
        fan = await s.get(Fan, (str(account_id), int(fan_id)))
        hard = await _hard_skip(account_id, fan_id, fan, s)
        walk = await _walk_advancing(account_id, fan_id, s)
        cfg = await _checkpoint(account_id, s)
    if cached:
        got = cached_listed(account_id, fan_id, cfg) if cfg is not None else None
        listed = got is not None and got.fresh and got.listed is True
    else:
        listed = int(fan_id) in await _listed(account_id, {int(fan_id)}, cfg, client)
    # The OF-app read only when nothing above it already stops the Turn (an off switch = 0 OF reads).
    human, human_at, his = await _human(account_id, int(fan_id), anchor_at, client,
                                        live_read and off is None and listed, ours)
    audience_ok, _why = await audience_allows_fan(account_id, fan_id, kind=AUDIENCE_KIND)
    return OwnerFacts(
        off=off, listed=listed, hard_skip=hard, audience_ok=bool(audience_ok), human=human, human_at=human_at,
        walk_advancing=walk, spend_cents=int(getattr(fan, "lifetime_spend_cents", 0) or 0),
        top_spend_cents=_top_spend_cents(cfg), fan_newest=his)


async def claimed_ids(account_id: str, fan_ids, *, client=None) -> set[int]:
    ids = {int(f) for f in fan_ids}
    if not ids:
        return set()
    async with get_session() as s:
        off = await _off(account_id, s)
        if not claims(off, True):
            return set()
        cfg = await _checkpoint(account_id, s)
    return await _listed(account_id, ids, cfg, client)


async def stand_down(account_id: str, fan_ids, *, lane: str, client=None) -> tuple[set[int], dict]:
    try:
        claimed = await claimed_ids(account_id, fan_ids, client=client)
    except Exception:
        log.warning("full_ai_stand_down_failed account=%s lane=%s", account_id, lane, exc_info=True)
        return set(), {}
    return claimed, ({"full_ai_claimed": len(claimed)} if claimed else {})
