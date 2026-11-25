from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Iterable, NamedTuple

from sqlalchemy import func, select

import of_paging
from audiences import resolve_window_hours
from db.engine import get_session
from db.models import (
    AccountAiConfig, Fan, List as ListModel, ListMember, Message,
)

log = logging.getLogger("of-relay.audience_include")

AUDIENCE_INCLUDE_KIND = "automation_include"
AUTOFENCE_KIND = "autofence"
AUTOFENCE_LIST_NAME = "AUTOFENCE"
# Grace covers sync health only: a stale snapshot still authorizes sends, never un-removes a fan
AUDIENCE_GRACE_HOURS_DEFAULT = 24.0
# of_paging backstop is 20k rows: a list at/above cannot be verified complete
AUDIENCE_MAX_LIST_ROWS = 20_000

AUDIENCE_MODES = ("off", "shadow", "enforce")


# Enforce halt: send NOTHING, never degrade to an unfenced/unscoped send
class AudienceHalt(RuntimeError):

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"audience_halt:{reason}" + (f" {detail}" if detail else ""))
        self.reason = reason


class AudiencePolicy(NamedTuple):
    mode: str
    configured_mode: str
    list_id: int | None
    of_list_id: int | None
    member_ids: frozenset
    synced_at: datetime | None
    healthy: bool
    paused: bool
    reason: str | None


_AUDIENCE_OFF = AudiencePolicy(
    mode="off", configured_mode="off", list_id=None, of_list_id=None,
    member_ids=frozenset(), synced_at=None, healthy=True, paused=False,
    reason=None,
)


# Corrupt value degrades to off: never raises on a send path, never enforces
def norm_audience_mode(v) -> str:
    s = str(v or "").strip().lower()
    return s if s in AUDIENCE_MODES else "off"


def _parse_sync_meta(raw) -> dict:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


async def automation_audience(account_id: str) -> AudiencePolicy:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
        mode = norm_audience_mode(getattr(cfg, "audience_mode", None))
        list_id = getattr(cfg, "audience_list_id", None) if cfg else None
        if mode == "off":
            return _AUDIENCE_OFF
        row = await s.get(ListModel, int(list_id)) if list_id is not None else None
        if (row is None or row.account_id != str(account_id)
                or row.kind != AUDIENCE_INCLUDE_KIND):
            # Config points at nothing usable: enforce fails closed, never unscopes to the full roster
            log.error("audience: account=%s mode=%s but include list %r is missing/foreign",
                      account_id, mode, list_id)
            return AudiencePolicy(
                mode=mode, configured_mode=mode, list_id=list_id, of_list_id=None,
                member_ids=frozenset(), synced_at=None, healthy=False,
                paused=False, reason="include_list_missing")
        members = (await s.execute(
            select(ListMember.fan_id).where(ListMember.list_id == int(row.id))
        )).scalars().all()

    meta = _parse_sync_meta(row.sync_meta_json)
    paused = bool(meta.get("paused"))
    grace_h = resolve_window_hours(meta.get("grace_hours"), AUDIENCE_GRACE_HOURS_DEFAULT)
    synced_at = row.synced_at
    effective = mode
    reason = None
    healthy = True
    if synced_at is None:
        # Enforcing an empty snapshot would darken the whole roster: sit in shadow until the mirror exists
        if mode == "enforce":
            effective, reason = "shadow", "pending_first_sync"
        healthy = False if mode == "enforce" else True
    else:
        age_h = max(0.0, (datetime.utcnow() - synced_at).total_seconds() / 3600.0)
        if bool(meta.get("truncated")):
            healthy, reason = False, "sync_truncated"
        elif grace_h and age_h > grace_h:
            healthy, reason = False, "snapshot_stale"
    return AudiencePolicy(
        mode=effective, configured_mode=mode, list_id=int(row.id),
        of_list_id=int(row.of_list_id) if row.of_list_id else None,
        member_ids=frozenset(int(m) for m in members),
        synced_at=synced_at, healthy=healthy, paused=paused,
        reason=reason)


class IncludeDecision(NamedTuple):
    kept: list[int]
    stats: dict
    dropped: list[int]
    halted: str | None
    with_intent: int


def include_decide(
    pol: AudiencePolicy, candidates: list[int], universe: set[int] | frozenset[int],
    intent: set[int] | frozenset[int],
) -> IncludeDecision:
    ids = list(candidates)
    if pol.mode == "off":
        return IncludeDecision(ids, {}, [], None, 0)
    stats: dict = {"audience_mode": pol.mode, "audience_before": len(ids)}
    dropped = [f for f in ids if f not in universe]
    with_intent = len([f for f in dropped if f in intent])
    if pol.mode == "shadow":
        stats.update(audience_skipped=len(dropped), audience_skipped_with_intent=with_intent)
        return IncludeDecision(ids, stats, dropped, None, with_intent)
    if pol.paused or not pol.healthy:
        why = "kill_switch" if pol.paused else (pol.reason or "unhealthy")
        held_intent = len([f for f in ids if f in intent])
        stats.update(audience_halted=why, audience_skipped=len(ids),
                     audience_skipped_with_intent=held_intent)
        return IncludeDecision([], stats, ids, why, held_intent)
    stats.update(audience_skipped=len(dropped), audience_skipped_with_intent=with_intent)
    return IncludeDecision([f for f in ids if f in universe], stats, dropped, None, with_intent)


async def filter_candidates(
    account_id: str,
    fan_ids,
    *,
    kind: str,
    policy: AudiencePolicy | None = None,
    stats: dict | None = None,
    intent_ids: Iterable[int] | None = None,
    extra_allowed_ids: Iterable[int] | None = None,
) -> list[int]:
    ids = [int(f) for f in (fan_ids or [])]
    pol = policy if policy is not None else await automation_audience(account_id)
    allowed = pol.member_ids | {int(x) for x in (extra_allowed_ids or [])}
    d = include_decide(pol, ids, allowed, {int(x) for x in (intent_ids or [])})
    if stats is not None:
        stats.update(d.stats)
    if d.halted:
        log.error("audience_halt account=%s kind=%s reason=%s — %d candidate(s) "
                  "held, nothing sent (pause never unscopes)",
                  account_id, kind, d.halted, len(ids))
    elif d.dropped and len(d.kept) == len(ids):
        log.info("audience_shadow account=%s kind=%s would_skip=%d of=%d "
                 "(with_intent=%d, snapshot=%s)",
                 account_id, kind, len(d.dropped), len(ids), d.with_intent, pol.synced_at)
    elif d.dropped:
        log.info("audience_enforced account=%s kind=%s kept=%d skipped=%d of=%d",
                 account_id, kind, len(d.kept), len(d.dropped), len(ids))
    return d.kept


async def audience_allows_fan(
    account_id: str,
    fan_id,
    *,
    kind: str,
    policy: AudiencePolicy | None = None,
) -> tuple[bool, str | None]:
    pol = policy if policy is not None else await automation_audience(account_id)
    if pol.mode == "off":
        return True, None
    inside = int(fan_id) in pol.member_ids
    if pol.mode == "shadow":
        if not inside:
            log.info("audience_shadow account=%s kind=%s fan=%s would_block",
                     account_id, kind, fan_id)
        return True, None
    if pol.paused:
        return False, "kill_switch"
    if not pol.healthy:
        return False, pol.reason or "unhealthy"
    return (True, None) if inside else (False, "outside_audience")


async def check_at_fire(
    account_id: str,
    fan_id,
    *,
    kind: str,
    payload: dict | None = None,
) -> tuple[bool, str | None]:
    # Operator-explicit sends bypass the audience by design; covers our queue only, not OF's native scheduler
    if isinstance(payload, dict) and str(payload.get("send_purpose") or "") == "manual":
        return True, "manual"
    return await audience_allows_fan(account_id, fan_id, kind=kind)




# Over-broad is the safe direction for an exclude fence
async def _audience_universe_ids(account_id: str) -> set[int]:
    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id).where(Fan.account_id == str(account_id))
        )).scalars().all()
    return {int(r) for r in rows if r is not None}


_crawl_list_ids_blocking = of_paging.list_member_ids


def _build_autofence_blocking(client, of_list_id, target: set[int]) -> dict:
    current, truncated = of_paging.list_member_ids(client, of_list_id)
    if truncated:
        raise AudienceHalt("fence_crawl_truncated",
                           f"list {of_list_id} member crawl incomplete (backstop or repeated page)")
    unaddable: set[int] = set()
    to_add = sorted(target - current)
    # adds BEFORE removals
    for uid in to_add:
        try:
            client.add_user_to_list(of_list_id, uid)
        except Exception as e:  # noqa: BLE001 — per-user tolerance, see docstring
            # Permanent OF add refusals (deleted/blocked/self id) are tolerated and dropped from the verify target; other failures halt
            if not of_paging.unlistable(e):
                raise AudienceHalt("fence_add_failed",
                                   f"list {of_list_id} add uid={uid} failed: "
                                   f"{str(e).splitlines()[0][:80] if str(e) else type(e).__name__}") from e
            unaddable.add(uid)
            log.warning("autofence add failed list=%s uid=%s (%s)",
                        of_list_id, uid, str(e).splitlines()[0][:80])
    for uid in sorted(current - target):
        try:
            client.remove_user_from_list(of_list_id, uid)
        except Exception as e:  # noqa: BLE001 — verify below decides if it matters
            log.warning("autofence remove failed list=%s uid=%s (%s)",
                        of_list_id, uid, str(e).splitlines()[0][:80])
    effective = target - unaddable
    after, truncated = of_paging.list_member_ids(client, of_list_id)
    if truncated:
        raise AudienceHalt("fence_verify_truncated",
                           f"list {of_list_id} verify crawl incomplete (backstop or repeated page)")
    diff = after ^ effective
    if diff:
        raise AudienceHalt(
            "fence_verify_diff",
            f"list {of_list_id} differs from target by {len(diff)} id(s) after rebuild")
    if unaddable:
        log.warning("autofence built with %d un-addable id(s) skipped list=%s "
                    "(size=%d)", len(unaddable), of_list_id, len(effective))
    return {"size": len(effective), "unaddable": len(unaddable)}


# Stored id is authoritative after first build; a short lists read halts, never mints a second AUTOFENCE
def _find_or_create_fence_blocking(client) -> int:
    try:
        lid = of_paging.find_list_id(client, AUTOFENCE_LIST_NAME)
    except of_paging.ListLookupIncomplete as e:
        raise AudienceHalt("fence_lookup_incomplete", str(e)) from e
    if lid is None:
        lid = client.create_list(AUTOFENCE_LIST_NAME).get("id")
    if lid is None:
        raise AudienceHalt("fence_create_failed", "OF returned no list id")
    return int(lid)


async def _persist_fence_state(
    account_id: str, *, of_list_id: int | None, healthy: bool,
    reason: str | None = None, size: int | None = None,
    unaddable: int | None = None,
) -> None:
    now = datetime.utcnow()
    meta = {"healthy": healthy, "reason": reason, "size": size,
            "unaddable": unaddable, "built_at": now.isoformat()}
    async with get_session() as s:
        row = (await s.execute(
            select(ListModel).where(
                ListModel.account_id == str(account_id),
                ListModel.kind == AUTOFENCE_KIND,
            )
        )).scalars().first()
        if row is None:
            row = ListModel(account_id=str(account_id), of_list_id=of_list_id,
                            name=AUTOFENCE_LIST_NAME, kind=AUTOFENCE_KIND,
                            is_system=True)
            s.add(row)
        if of_list_id is not None and not row.of_list_id:
            row.of_list_id = int(of_list_id)
        if healthy:
            row.synced_at = now
        row.sync_meta_json = json.dumps(meta)


async def ensure_autofence(
    account_id: str,
    *,
    client=None,
    policy: AudiencePolicy | None = None,
) -> int | None:
    pol = policy if policy is not None else await automation_audience(account_id)
    if pol.mode != "enforce":
        return None
    if pol.paused:
        raise AudienceHalt("kill_switch", "audience automation is paused")
    if not pol.healthy:
        raise AudienceHalt(pol.reason or "mirror_unhealthy",
                           "include mirror is not a trustworthy snapshot")
    # Caller holds broadcast_lock; this must NOT re-take it
    universe = await _audience_universe_ids(account_id)
    target = universe - pol.member_ids
    if len(target) > AUDIENCE_MAX_LIST_ROWS:
        await _persist_fence_state(account_id, of_list_id=None, healthy=False,
                                   reason="fence_scale")
        raise AudienceHalt("fence_scale",
                           f"fence would need {len(target)} rows (bound "
                           f"{AUDIENCE_MAX_LIST_ROWS}) — enforcement unsupported")
    c = client
    if c is None:
        import automation_executor as ax
        c = await asyncio.to_thread(ax._make_client, account_id)
    async with get_session() as s:
        row = (await s.execute(
            select(ListModel).where(
                ListModel.account_id == str(account_id),
                ListModel.kind == AUTOFENCE_KIND,
            )
        )).scalars().first()
        of_lid = int(row.of_list_id) if (row is not None and row.of_list_id) else None
    try:
        if of_lid is None:
            of_lid = await asyncio.to_thread(_find_or_create_fence_blocking, c)
        built = await asyncio.to_thread(_build_autofence_blocking, c, of_lid, target)
    except AudienceHalt as e:
        await _persist_fence_state(account_id, of_list_id=of_lid, healthy=False,
                                   reason=e.reason)
        raise
    except Exception as e:
        await _persist_fence_state(account_id, of_list_id=of_lid, healthy=False,
                                   reason="fence_build_error")
        raise AudienceHalt("fence_build_error", str(e).splitlines()[0][:120]) from e
    await _persist_fence_state(account_id, of_list_id=of_lid, healthy=True,
                               size=built["size"], unaddable=built["unaddable"])
    log.info("autofence ok account=%s list=%s size=%d unaddable=%d",
             account_id, of_lid, built["size"], built["unaddable"])
    return of_lid


async def audience_fence_for_broadcast(
    account_id: str,
    *,
    client=None,
    policy: AudiencePolicy | None = None,
    stats: dict | None = None,
) -> list[int]:
    pol = policy if policy is not None else await automation_audience(account_id)
    if stats is not None and pol.mode != "off":
        stats["audience_mode"] = pol.mode
    if pol.mode == "off":
        return []
    if pol.mode == "shadow":
        universe = await _audience_universe_ids(account_id)
        would = len(universe - pol.member_ids)
        if stats is not None:
            stats["audience_fence_would_exclude"] = would
            stats["audience_universe"] = len(universe)
        log.info("audience_shadow account=%s mass fence would exclude %d of %d "
                 "known fans", account_id, would, len(universe))
        return []
    fence_id = await ensure_autofence(account_id, client=client, policy=pol)
    if stats is not None and fence_id is not None:
        stats["audience_fence_list_id"] = int(fence_id)
    return [int(fence_id)] if fence_id is not None else []



AUDIENCE_SEND_PURPOSE_BASES = ("gated", "fenced", "manual", "exempt", "not_fan_dm")


def audit_send_purpose(purpose, *, where: str = "send") -> None:
    ok = purpose is not None and \
        str(purpose).split(":", 1)[0] in AUDIENCE_SEND_PURPOSE_BASES
    if ok:
        return
    msg = (f"send_purpose missing/unknown ({purpose!r}) at {where} — every "
           f"automation-originated fan DM must declare one of "
           f"{AUDIENCE_SEND_PURPOSE_BASES}")
    from automations._knobs import test_mode
    if test_mode():
        raise AssertionError(msg)
    log.error("send_purpose_untagged where=%s purpose=%r", where, purpose)


# Every send-capable file in automations/ must appear; tests/test_audience_coverage.py fails on any unclassified sender
AUDIENCE_SENDER_CLASSIFICATION: dict[str, str] = {
    "welcome_chatter_for_info": "gated",
    "autoreply": "gated",
    "send_followup": "gated",
    "cat_stickers": "gated",
    "reply_mass_funnel": "gated",
    "send_welcome": "gated",
    "scheduled_send": "gated",
    "nudge_online_fire": "gated",
    "purchase_followup": "gated",
    "lifecycle_messages": "gated",
    "expiry_message": "gated",
    "expired_message": "gated",
    "resubscribe_message": "gated",
    "birthday_message": "gated",
    "priority_mass": "gated",
    "full_ai_ppv": "gated",
    "full_ai_live": "gated",
    "send_mass_message": "fenced",
    "mass_premade": "fenced",       # pure delegation (test asserts no bypass)
    # exempt, named reason (printed in the Brain UI exemption register)
    "unsend_messages": "exempt:cleanup — removes messages, sends nothing new",
    "pacing": "exempt:infrastructure — paces writes, never originates a send",
    "_send_failure": "exempt:the shared send seam itself",
    "_common": "exempt:re-export shim — no send code; the scan matches the re-exported name",
    "full_ai_look": "exempt:the last look — no send code; it gates full_ai_live / full_ai_ppv's sends "
                    "(the scan matches its before_write hook's name)",
    "auto_posts": "not_fan_dm",
    "auto_stories": "not_fan_dm",
    "s4s_post": "not_fan_dm",
    "smart_list_sync": "not_fan_dm",
}


async def established_fan_ids(
    account_id: str, fan_ids, *, max_outbound: int, max_inbound: int
) -> set[int]:
    if not fan_ids:
        return set()
    ids = [int(f) for f in fan_ids]
    out_c: dict[int, int] = {}
    in_c: dict[int, int] = {}
    async with get_session() as s:
        rows = (await s.execute(
            select(Message.fan_id, Message.direction, func.count())
            .where(Message.account_id == str(account_id), Message.fan_id.in_(ids))
            .group_by(Message.fan_id, Message.direction)
        )).all()
    for fid, direction, cnt in rows:
        if direction == "out":
            out_c[int(fid)] = int(cnt)
        elif direction == "in":
            in_c[int(fid)] = int(cnt)
    return {
        fid for fid in ids
        if out_c.get(fid, 0) > max_outbound or in_c.get(fid, 0) > max_inbound
    }
