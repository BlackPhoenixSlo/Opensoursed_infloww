"""automations/full_ai_owner_io.py — the reads behind `full_ai_owner` (spec 04b › Solution, Contracts).

  load(account_id, fan_id, anchor_at, *, client=None, live_read=False) -> OwnerFacts
        every fact `who_owns` reads, at one Evaluation point (job start, each bubble)
  claimed_ids(account_id, fan_ids, *, client=None) -> set[int]
        the Fans Full AI claims, for the other Lanes' candidate seams (batch)
  _listed(...)  the Fans list through Auto-reply's `_folder_members` (both lists empty = no OF call)
  stand_down(account_id, fan_ids, *, lane) -> (claimed, stats)
        one call at another reply Lane's candidate seam: the Fans to drop and the run's stats
  start_human_yield(account_id, fan_id, sent_at)
        the OF-app Human yield's quiet time: the shared per-fan cooldown, never shortened
  _live(account_id) -> bool
        the Mode gate. False on main: no Creator is live, so `off` is always `off_mode` and
        `claimed_ids` is empty. Ticket 81 points it at `full_ai_live.live_rule` (never a `mode ==` check).

Reads only (DB rows, the global switch). No funnel code is edited.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

import job_queue
import runtime_switches
from audience_include import audience_allows_fan
from automations import _human_outbound
from automations import full_ai_config
from automations._skiplist import HARD_SKIP_REASONS, should_skip_muted_creator
from automations.full_ai_owner import OwnerFacts, claims, in_fans, of_app_human, yield_left_s
from db.engine import get_session
from db.models import AccountAiConfig, Blacklist, Fan, FunnelState, MassRun, Message, SkipList

log = logging.getLogger(__name__)

KIND = "full_ai_chat"
OFF_SWITCH = "FULL_AI_CHAT_OFF"
AUDIENCE_KIND = "full_ai_live"
# The hard skip_list reasons plus `unreachable` (a dead chat): a graduation reason is not one.
HARD_REASONS: frozenset[str] = frozenset(HARD_SKIP_REASONS | {"unreachable"})
REPLY_FUNNEL_KIND = "reply_mass_funnel"


async def _live(account_id: str) -> bool:
    """The Mode gate. False on main (no Creator is live); ticket 81 wires it."""
    return False


async def _off(account_id: str, s) -> str | None:
    """Row 1: the first off reason, or None when Full AI is on for this Creator."""
    if runtime_switches.on(OFF_SWITCH):
        return "off_global"
    if await job_queue.enabled_rule_id(account_id, KIND, session=s) is None:
        return "off_rule"
    if not await _live(account_id):
        return "off_mode"
    return None


async def _checkpoint(account_id: str, s) -> dict:
    """The Creator's checkpoint side (what live runs on), DEFAULTS-filled."""
    row = await s.get(AccountAiConfig, str(account_id))
    raw = row.full_ai_config_json if row is not None else None
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        log.warning("full_ai_owner bad config json account=%s", account_id)
        stored = {}
    return full_ai_config.merged(stored)["checkpoint"]


def _top_spend_cents(cfg: dict) -> int:
    """`top_spend_cents` off a side; a stored value that is not a whole number >= 0 reads the default."""
    v = cfg.get("top_spend_cents")
    if type(v) is int and v >= 0:
        return v
    return full_ai_config.DEFAULTS["top_spend_cents"]


async def _members(account_id: str, client, list_ids: list[int]) -> frozenset | None:
    """Fans on any of `list_ids`: Auto-reply's shipped crawl (5 min cache, None on a failed read)."""
    from automations import autoreply   # lazy: autoreply imports this module inside its run
    return await autoreply._folder_members(account_id, client, tuple(sorted(set(list_ids))))


async def _listed(account_id: str, fan_ids: set[int], cfg: dict, client=None) -> set[int]:
    """The Fans of `fan_ids` on the Fans list (`in_fans`). Both lists empty: everyone, no OF client
    built, no OF call. A malformed stored list, a client that will not build or a failed read: the
    Fans on it are not listed (never widen)."""
    fans = cfg.get("fans")
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
        on_exc = await _members(account_id, client, exc) if exc else frozenset()
    except Exception:
        log.warning("full_ai_owner fans list read failed account=%s", account_id, exc_info=True)
    return {f for f in fan_ids
            if in_fans(fans, None if on_inc is None else f in on_inc, None if on_exc is None else f in on_exc)}


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
    """A pending funnel_state under this account's mass run, its walker's rule on
    (`reply_mass_funnel`)."""
    rows = (await s.execute(
        select(FunnelState.last_error, MassRun.automation_kind)
        .join(MassRun, MassRun.id == FunnelState.mass_run_id)
        .where(MassRun.account_id == str(account_id), FunnelState.fan_id == int(fan_id),
               FunnelState.status == "pending"))).all()
    return bool(rows) and await job_queue.enabled_rule_id(
        account_id, REPLY_FUNNEL_KIND, session=s) is not None


async def _human(account_id: str, fan_id: int, anchor_at: datetime, client,
                 live_read: bool) -> tuple[str | None, datetime | None]:
    """Row 5: ("human", None) for a human's 1:1 row since the anchor (DB, every call; its cooldown is
    already set by `write_outbound_attribution`); else, with `live_read` and a client, one OF read:
    ("human_of_app", its send time). A failed read = no Stop."""
    if await _human_outbound.manual_outbound_since(account_id, fan_id, since=anchor_at):
        return "human", None
    if not live_read or client is None:
        return None, None
    try:
        data = await asyncio.to_thread(lambda: client.get_messages(fan_id, limit=10))
        items = data.get("list") if isinstance(data, dict) else data
        items = [m for m in items or [] if isinstance(m, dict)]
        ids = {int(m["id"]) for m in items if isinstance(m.get("id"), (int, str)) and str(m["id"]).isdigit()}
        known: set[int] = set()
        if ids:
            async with get_session() as s:
                known = set((await s.execute(select(Message.message_id).where(
                    Message.account_id == str(account_id), Message.fan_id == int(fan_id),
                    Message.message_id.in_(ids)))).scalars())
        at = of_app_human(items, fan_id=int(fan_id), anchor_at=anchor_at, known_ids=known)
    except Exception:
        log.warning("full_ai_owner OF-app read failed account=%s fan=%s", account_id, fan_id, exc_info=True)
        return None, None
    return ("human_of_app", at) if at is not None else (None, None)


async def start_human_yield(account_id: str, fan_id: int, sent_at: datetime) -> None:
    """Rest the Fan for what is left of the Human yield after a human's OF-app send at `sent_at`
    (`attribution._manual_yield_seconds`): the existing shared cooldown, nothing new. No write when
    nothing is left, or when a longer rest already stands."""
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
               live_read: bool = False) -> OwnerFacts:
    """Every fact `who_owns` reads for this Fan now. `anchor_at`: his Turn's anchor (the human
    rows look after it); `client` / `live_read`: the OF-app read (ticket 79)."""
    async with get_session() as s:
        off = await _off(account_id, s)
        fan = await s.get(Fan, (str(account_id), int(fan_id)))
        hard = await _hard_skip(account_id, fan_id, fan, s)
        walk = await _walk_advancing(account_id, fan_id, s)
        cfg = await _checkpoint(account_id, s)
    listed = int(fan_id) in await _listed(account_id, {int(fan_id)}, cfg, client)
    human, human_at = await _human(account_id, int(fan_id), anchor_at, client, live_read)
    audience_ok, _why = await audience_allows_fan(account_id, fan_id, kind=AUDIENCE_KIND)
    return OwnerFacts(
        off=off, listed=listed, hard_skip=hard, audience_ok=bool(audience_ok), human=human, human_at=human_at,
        walk_advancing=walk, spend_cents=int(getattr(fan, "lifetime_spend_cents", 0) or 0),
        top_spend_cents=_top_spend_cents(cfg))


async def claimed_ids(account_id: str, fan_ids, *, client=None) -> set[int]:
    """The Fans of `fan_ids` Full AI claims (`claims`); empty, with no OF call, while Full AI is off
    for the Creator."""
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
    """For another reply Lane's candidate seam (Get to know fans, Auto-reply): (the claimed Fans to drop,
    stats). Stats is {"full_ai_claimed": n} when n > 0, else {} so a run Full AI claims nobody from returns
    today's keys byte for byte. `claimed_ids` raising: nobody is claimed and one warning is logged (a Full
    AI fault never silences the other Lanes). `client`: the Lane's OF client if it already has one (the
    Fans list read reuses it)."""
    try:
        claimed = await claimed_ids(account_id, fan_ids, client=client)
    except Exception:
        log.warning("full_ai_stand_down_failed account=%s lane=%s", account_id, lane, exc_info=True)
        return set(), {}
    return claimed, ({"full_ai_claimed": len(claimed)} if claimed else {})
