from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from automation_registry import register
from db.engine import get_session
from db.models import Fan, SkipList
from ._common import HARD_SKIP_REASONS, coerce_ids
from .apply_profiles import run as apply_profiles_run
from .gen_info import run as gen_info_run

log = logging.getLogger("of-relay.automation.process_old_fans")

_SKIP_REASON = "old_fan_pre_ai"
# Hard restricts (muted_creator, manual_restrict) are deliberate no-automation states, not a bare row to override.
_ONBOARDED_REASONS = frozenset({_SKIP_REASON}) | HARD_SKIP_REASONS



async def _resolve_usernames(account_id: str, usernames: list[str]) -> tuple[set[int], list[str]]:
    wanted = {u.lstrip("@").strip().lower() for u in usernames if u and u.strip()}
    if not wanted:
        return set(), []
    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id, func.lower(Fan.of_username)).where(
                Fan.account_id == str(account_id),
                func.lower(Fan.of_username).in_(list(wanted)),
            )
        )).all()
    by_name = {name: int(fid) for fid, name in rows if name}
    resolved = {fid for fid in by_name.values()}
    unresolved = sorted(wanted - set(by_name))
    return resolved, unresolved



async def _recent_fan_ids(account_id: str, recent_limit: int, recent_by: str) -> set[int]:
    order_col = (Fan.last_message_received_at if recent_by == "messaged"
                 else Fan.subscribed_at)
    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id)
            .where(Fan.account_id == str(account_id))
            .order_by(order_col.desc())
            .limit(int(recent_limit))
        )).all()
    return {int(r[0]) for r in rows}



async def _already_onboarded(account_id: str, ids: set[int]) -> set[int]:
    if not ids:
        return set()
    async with get_session() as s:
        rows = (await s.execute(
            select(SkipList.fan_id).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id.in_(list(ids)),
                SkipList.reason.in_(tuple(_ONBOARDED_REASONS)),
            )
        )).all()
    return {int(r[0]) for r in rows}



# Both upserts do_nothing: an existing skip row (any reason) is preserved.
async def _flag_fans(account_id: str, ids: set[int], now: datetime) -> int:
    flagged = 0
    async with get_session() as s:
        for fid in ids:
            await s.execute(
                sqlite_insert(SkipList)
                .values(account_id=str(account_id), fan_id=int(fid),
                        reason=_SKIP_REASON, added_at=now)
                .on_conflict_do_nothing(index_elements=["account_id", "fan_id"])
            )
            await s.execute(
                sqlite_insert(Fan)
                .values(account_id=str(account_id), fan_id=int(fid),
                        updated_at=now)
                .on_conflict_do_nothing(index_elements=["account_id", "fan_id"])
            )
            flagged += 1
    return flagged



@register("process_old_fans")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Onboard a batch of pre-AI fans: flag them out of the AI chatter, then
    (unless flag_only) profile + apply over the batch via gen_info + apply_profiles.

    payload:
      fan_ids:      [int|str, …]  numeric old-fan ids (the sheet's column A).
      usernames:    [str, …]      `@user` sheet rows, resolved via fans.of_username.
      recent_limit: int           NO fan_ids/usernames → take the N most-recent fans.
      recent_by:    str           "subscribed" (default) | "messaged" — orders that
                                  fallback by subscribed_at / last_message_received_at.
      model:        str           override forwarded to gen_info.
      limit:        int           sweep ceiling forwarded to gen_info + apply_profiles.
      flag_only:    bool          only flip DB flags (the spec's --no-scrape).
      reprocess:    bool          re-run even fans already onboarded.
    """
    payload = payload or {}
    fan_ids = coerce_ids(payload.get("fan_ids"))
    raw_usernames = payload.get("usernames")
    usernames = [str(u) for u in raw_usernames] if isinstance(raw_usernames, (list, tuple)) else []
    flag_only = bool(payload.get("flag_only"))
    reprocess = bool(payload.get("reprocess"))

    resolved_ids, unresolved = await _resolve_usernames(account_id, usernames)
    old_ids = set(fan_ids) | resolved_ids

    if not fan_ids and not usernames and payload.get("recent_limit"):
        recent_by = str(payload.get("recent_by") or "subscribed").lower()
        if recent_by not in ("subscribed", "messaged"):
            recent_by = "subscribed"
        old_ids = await _recent_fan_ids(account_id, int(payload["recent_limit"]), recent_by)

    if not old_ids:
        return {
            "old_fans": 0,
            "unresolved_usernames": len(unresolved),
            "flagged": 0,
            "processed": 0,
            "note": "no old-fan ids in payload",
        }

    already = set() if reprocess else await _already_onboarded(account_id, old_ids)
    to_process = old_ids - already

    now = datetime.utcnow()
    flagged = await _flag_fans(account_id, old_ids, now)

    gen_stats: dict | None = None
    apply_stats: dict | None = None
    if not flag_only and to_process:
        sub_payload: dict = {"force_ids": sorted(to_process)}
        if payload.get("model"):
            sub_payload["model"] = payload["model"]
        if payload.get("limit"):
            sub_payload["limit"] = int(payload["limit"])
        if payload.get("push_to_of"):
            sub_payload["push_to_of"] = True

        try:
            gen_stats = await gen_info_run(account_id, sub_payload, run_id=run_id)
        except Exception:
            log.warning("process_old_fans_gen_info_failed account=%s", account_id, exc_info=True)
        try:
            apply_stats = await apply_profiles_run(account_id, sub_payload, run_id=run_id)
        except Exception:
            log.warning("process_old_fans_apply_failed account=%s", account_id, exc_info=True)

    return {
        "old_fans": len(old_ids),
        "unresolved_usernames": len(unresolved),
        "already_onboarded": len(already),
        "flagged": flagged,
        "processed": len(to_process),
        "flag_only": flag_only,
        "gen_info": gen_stats,
        "apply_profiles": apply_stats,
    }
