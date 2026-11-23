"""automations/full_ai_owner_io.py — the reads behind `full_ai_owner` (spec 04b › Solution, Contracts).

  off_reason(account_id) -> str | None   row 1 alone (the switch, the rule, the Mode)
  global_off() -> str | None             the switch alone ("off_global"), no I/O
  load(account_id, fan_id, anchor_at, *, client=None, live_read=False, cached=False) -> OwnerFacts
        every fact `who_owns` reads, at one Evaluation point (job start, each bubble); `cached` (the
        write gate's re-look): the Fans list off `cached_listed` only, fail closed
  claimed_ids(account_id, fan_ids, *, client=None) -> set[int]
        the Fans Full AI claims, for the other Lanes' candidate seams (batch)
  _listed(...)  the Fans list through Auto-reply's `_folder_members` (both lists empty = no OF call)
  cached_listed(account_id, fan_id, cfg) -> FansRead
        the same verdict off that read's in-process cache only (never an OF call), for the help bot
        and the live write gate
  stand_down(account_id, fan_ids, *, lane) -> (claimed, stats)
        one call at another reply Lane's candidate seam: the Fans to drop and the run's stats
  start_human_yield(account_id, fan_id, sent_at)
        the OF-app Human yield's quiet time: the shared per-fan cooldown, never shortened
  _live(account_id) -> bool
        the Mode gate: the Creator's enabled rule is in Mode live (`full_ai_live.live_rule`, never a
        `mode ==` check). False for every Creator until ticket 74's flip.

Reads only (DB rows, the global switch). No funnel code is edited: a run's walker and its hold mark
are `_funnel_walkers`'; the human-send rule is `_human_outbound`'s.
"""
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
# The hard skip_list reasons plus `unreachable` (a dead chat): a graduation reason is not one.
HARD_REASONS: frozenset[str] = frozenset(HARD_SKIP_REASONS | {"unreachable"})


async def _live(account_id: str) -> bool:
    """The Mode gate: the Creator's enabled full_ai_chat rule is in Mode live."""
    from automations import full_ai_live   # lazy: full_ai_live imports this module (its last look, `full_ai_look`)
    return await full_ai_live.live_rule(account_id) is not None


def global_off() -> str | None:
    """"off_global" when the global switch is on, else None (no I/O: `full_ai_look.gate` re-checks it last)."""
    return "off_global" if runtime_switches.on(OFF_SWITCH) else None


async def _off(account_id: str, s) -> str | None:
    """Row 1: the first off reason, or None when Full AI is on for this Creator."""
    if (off := global_off()) is not None:
        return off
    if await job_queue.enabled_rule_id(account_id, KIND, session=s) is None:
        return "off_rule"
    if not await _live(account_id):
        return "off_mode"
    return None


async def off_reason(account_id: str) -> str | None:
    """`_off` in its own session: a live job's first check (no OF read, no vision call before it)."""
    async with get_session() as s:
        return await _off(account_id, s)


async def _checkpoint(account_id: str, s) -> dict | None:
    """The Creator's checkpoint side (what live runs on), DEFAULTS-filled; None when the stored blob will
    not read (`full_ai_config.loaded`): nobody is listed."""
    row = await s.get(AccountAiConfig, str(account_id))
    got = full_ai_config.loaded(row.full_ai_config_json if row is not None else None)
    if got is None:
        log.warning("full_ai_owner bad config json account=%s: nobody listed", account_id)
        return None
    return got["checkpoint"]


def _top_spend_cents(cfg: dict | None) -> int:
    """`top_spend_cents` off a side; a stored value that is not a whole number >= 0 reads the default."""
    v = (cfg or {}).get("top_spend_cents")
    if type(v) is int and v >= 0:
        return v
    return full_ai_config.DEFAULTS["top_spend_cents"]


# (account, exclude list ids) -> when the short read last warned about was made (monotonic): one warning per crawl.
_short_warned: dict[tuple[str, tuple[int, ...]], float] = {}


def _short(account_id: str, list_ids, p) -> bool:
    """The exclusion list's cached read `p` (`autoreply.FolderPeek`) stopped short (paging backstop): Full AI
    reads it as no read, never a partial set, so it claims nobody on the account until a full read
    (fail closed). Warns once per crawl."""
    if p is None or p.members is None or not p.partial:
        return False
    key, at = (str(account_id), tuple(sorted({int(x) for x in list_ids}))), time.monotonic() - (p.read_age_s or 0.0)
    if abs(_short_warned.get(key, float("-inf")) - at) > 1.0:
        _short_warned[key] = at
        log.warning("full_ai_owner exclude list read short (paging backstop) account=%s lists=%s: Full AI "
                    "claims no Fan on this account until a full read", account_id, list(key[1]))
    return True


async def _members(account_id: str, client, list_ids: list[int], *, whole: bool = False) -> frozenset | None:
    """Fans on any of `list_ids`: Auto-reply's shipped crawl (5 min cache, None on a failed read).
    `whole` (the exclusion list): a short read (paging backstop) is None too, never a partial set (`_short`)."""
    from automations import autoreply   # lazy: autoreply imports this module inside its run
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
    """`cached_listed`'s answer: the Fans list verdict off the last OnlyFans reads in this process."""
    listed: bool | None          # in_fans' verdict; None = a needed list has no read cached (unknown)
    age_s: float | None          # the OLDEST good read it rests on; None = no read needed / none
    failed_age_s: float | None   # the newest read of a needed list FAILED this long ago (never fresh:
                                 # nothing is cached on a failure, so the next Turn reads again)
    fresh: bool                  # every read it rests on is inside the cache window: what Full AI acts on now


def cached_listed(account_id: str, fan_id: int, cfg: dict) -> FansRead:
    """`_listed` for one Fan from Auto-reply's folder cache ONLY (`autoreply.peek_folder`): no client, no
    OF call, ever. A failed newest read = not listed THEN, as `_listed` treated it; same `in_fans`."""
    from automations import autoreply   # lazy: autoreply imports this module inside its run
    fans = cfg.get("fans")
    if full_ai_config._fans_error(fans) is not None:
        return FansRead(False, None, None, True)
    ttl = autoreply._FOLDER_TTL_S
    on: list[bool | None] = []   # per list (include, exclude); None = failed read / empty list (ignored)
    ages: list[float] = []
    failed: list[float] = []
    unknown = False
    for whole, ids in ((False, fans["include"]), (True, fans["exclude"])):
        p = autoreply.peek_folder(account_id, ids) if ids else None
        if whole and _short(account_id, ids, p):
            p = p._replace(members=None)            # a short exclusion read: unknown (as `_members`)
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
    """A pending funnel_state under this account's mass run, not held, its walker's rule on
    (`_funnel_walkers.walker_for` the run's kind; `reply_mass_funnel` by default)."""
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
    """Row 5: ("human", None, None) for a human's 1:1 row since the anchor (DB, every call; its cooldown
    is already set by `write_outbound_attribution`); else, with `live_read` and a client, one OF read:
    ("human_of_app", its send time) when a human answered, and the Fan's newest item after the anchor
    (`fan_after`, else None). `ours`: OF ids known ours besides the `messages` rows (the Turn's sent
    bubbles, should a best-effort attribution write have failed). A failed read = no Stop."""
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
               live_read: bool = False, ours: frozenset[int] | set[int] = frozenset(),
               cached: bool = False) -> OwnerFacts:
    """Every fact `who_owns` reads for this Fan now. `anchor_at`: his Turn's anchor (the human
    rows look after it); `client` / `live_read`: the OF-app read (ticket 79); `ours`: OF ids of
    the Turn's own sent bubbles, never a human's. `cached`: the Fans list off `cached_listed`
    only (no OF call); a list with no read cached, a failed or a stale read = not listed."""
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
