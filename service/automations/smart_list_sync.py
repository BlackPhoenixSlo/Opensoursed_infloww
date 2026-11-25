from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import delete, or_, select, update

from audience_include import _crawl_list_ids_blocking
from automation_registry import register
from db.engine import get_session
from db.models import SmartList
from of_client import OFAPIError
from side_effect_gate import PLATFORM_LACKS_PREFIX, refusal

log = logging.getLogger("of-relay.automation.smart_list_sync")

_KIND = "smart_list_sync"
_SEND_PURPOSE = "not_fan_dm"
# Leftover waits for the next run, which also bounds how fast a wrong target could empty a list.
_MAX_WRITES_PER_RUN = 40  # ≈7.5 min of paced writes per run, all lists together
_ADD_CHUNK = 100
_MAX_MEMBERS = 19_000  # under the 20k crawl backstop
_ROSTER_USABLE = ("crawled", "fresh")


def _not_found(e: Exception) -> bool:
    return getattr(getattr(e, "response", None), "status_code", None) == 404


def _short(e: Exception) -> str:
    return (str(e).splitlines() or [type(e).__name__])[0][:160]


async def _write(account_id: str, fn):
    import automation_executor as ax
    return await ax.of_write_paced(account_id, fn, send_purpose=_SEND_PURPOSE)


async def _save(list_id: int, **values) -> None:
    async with get_session() as s:
        await s.execute(update(SmartList).where(SmartList.id == list_id).values(**values))


async def _claim(list_id: int) -> SmartList | None:
    async with get_session() as s:
        res = await s.execute(
            # Only one run per (account, kind) is in flight, so a row still syncing now was left by a crash.
            update(SmartList)
            .where(SmartList.id == list_id, SmartList.is_active.is_(True),
                   or_(SmartList.sync_state.is_(None), SmartList.sync_state != "syncing"))
            .values(sync_state="syncing"))
        if res.rowcount != 1:
            return None
        row = await s.get(SmartList, list_id)
        s.expunge(row)
        return row


def _confirmed(resp, of_list_id: int, chunk: list[int]) -> set[int]:
    if not isinstance(resp, dict):
        return set(chunk)
    echoed = resp.get(str(of_list_id), resp.get(of_list_id))
    if not isinstance(echoed, list):
        return set(chunk)
    ids = set()
    for x in echoed:
        try:
            ids.add(int(x["id"] if isinstance(x, dict) else x))
        except (KeyError, TypeError, ValueError):
            continue
    return ids & set(chunk)


class _Run:

    def __init__(self, account_id: str, client):
        self.account_id = account_id
        self.client = client
        self.budget = _MAX_WRITES_PER_RUN
        self.roster: str | None = None

    async def write(self, fn):
        self.budget -= 1
        return await _write(self.account_id, fn)


async def _sync_one(run: _Run, row: SmartList) -> dict:
    from smart_lists_api import (
        _load_normalised_fans, _rules_of, resolve, uses_subscription_facts,
    )
    from automations.lifecycle_messages import refresh_roster

    rules = _rules_of(row)
    if uses_subscription_facts(rules):
        if run.roster is None:
            res = await refresh_roster(run.account_id, run.client, now=datetime.utcnow())
            run.roster = str(res.get("roster"))
        if run.roster not in _ROSTER_USABLE:
            return {"sync_state": "error",
                    "sync_error": f"subscriber roster unavailable ({run.roster}) — nothing synced"}
    fans = await _load_normalised_fans(run.account_id, rules,
                                       roster_fresh=run.roster in _ROSTER_USABLE)
    target = set(resolve(rules, fans))
    if len(target) > _MAX_MEMBERS:
        return {"sync_state": "error",
                "sync_error": f"{len(target)} fans match — lists above {_MAX_MEMBERS} are not synced"}

    of_list_id = row.of_list_id
    if of_list_id is None:
        if run.budget <= 0:
            return {"sync_state": "pending", "sync_error": None}
        created = await run.write(lambda: run.client.create_list(row.name))
        new_id = created.get("id") if isinstance(created, dict) else None
        if not new_id:
            return {"sync_state": "error", "sync_error": "OnlyFans did not return a list id"}
        of_list_id = int(new_id)
        # Persist at once: the next run must find it, never create a second list.
        await _save(row.id, of_list_id=of_list_id, of_list_name=row.name)
        row.of_list_name = row.name

    try:
        members, truncated = await asyncio.to_thread(
            _crawl_list_ids_blocking, run.client, of_list_id)
    except OFAPIError as e:
        if _not_found(e):
            return {"sync_state": "error", "of_list_id": None, "of_list_name": None,
                    "member_count": None,
                    "sync_error": "the OnlyFans list was deleted there — a new one is "
                                  "created on the next sync"}
        raise
    if truncated:
        return {"sync_state": "error",
                "sync_error": "OnlyFans list crawl incomplete (20k backstop) — nothing synced"}
    # Rename only after the crawl has shown the list still exists on OF.
    if row.of_list_name != row.name and run.budget > 0:
        await run.write(lambda: run.client.rename_list(of_list_id, row.name))
        await _save(row.id, of_list_name=row.name)

    adds = sorted(target - members)
    removes = sorted(members - target)
    if removes and not fans:
        return {"sync_state": "error",
                "sync_error": "no fans stored for this creator — removals held"}

    added = unconfirmed = removed = failed = 0
    left = len(adds) + len(removes)
    for i in range(0, len(adds), _ADD_CHUNK):
        if run.budget <= 0:
            break
        chunk = adds[i:i + _ADD_CHUNK]
        left -= len(chunk)
        try:
            resp = await run.write(
                lambda c=chunk: run.client.add_users_to_lists({str(of_list_id): c}))
        except Exception as e:  # noqa: BLE001 — retried next run
            failed += len(chunk)
            log.warning("smart_list_sync add failed list=%s (%s)", row.id, _short(e))
            continue
        ok = _confirmed(resp, of_list_id, chunk)
        added += len(ok)
        unconfirmed += len(chunk) - len(ok)
    for fid in removes:
        if run.budget <= 0:
            break
        left -= 1
        try:
            await run.write(lambda f=fid: run.client.remove_user_from_list(of_list_id, f))
            removed += 1
        except Exception as e:  # noqa: BLE001 — retried next run
            if _not_found(e):
                removed += 1
                continue
            failed += 1
            log.warning("smart_list_sync remove failed list=%s fan=%s (%s)",
                        row.id, fid, _short(e))

    notes = []
    if unconfirmed:
        notes.append(f"{unconfirmed} fans could not be added on OnlyFans")
    if failed:
        notes.append(f"{failed} OnlyFans writes failed — retried next sync")
    log.info("smart_list_sync list=%s of_list=%s target=%d members=%d +%d -%d left=%d",
             row.id, of_list_id, len(target), len(members), added, removed, left)
    return {"sync_state": "pending" if (left or failed) else "ok",
            "sync_error": "; ".join(notes) or None,
            "synced_at": datetime.utcnow(),
            "member_count": len(members) + added - removed}


async def _finish_tombstone(run: _Run, list_id: int, of_list_id: int | None) -> bool:
    if of_list_id is not None:
        if run.budget <= 0:
            return False
        try:
            await run.write(lambda: run.client.delete_list(of_list_id))
        except Exception as e:  # noqa: BLE001 — the tombstone retries next run
            if not _not_found(e):
                log.warning("smart_list_sync delete of OF list %s failed (%s)",
                            of_list_id, _short(e))
                return False
    from smart_lists_api import DELETING
    async with get_session() as s:
        await s.execute(delete(SmartList).where(
            SmartList.id == list_id, SmartList.sync_state == DELETING))
    log.info("smart_list_sync account=%s deleted OF list %s (smart list %s)",
             run.account_id, of_list_id, list_id)
    return True


@register(_KIND)
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    from smart_lists_api import DELETING
    async with get_session() as s:
        await s.execute(
            update(SmartList)
            .where(SmartList.account_id == str(account_id), SmartList.sync_state == "syncing")
            .values(sync_state="error", sync_error="previous sync was interrupted"))
        tombstones = (await s.execute(
            select(SmartList.id, SmartList.of_list_id)
            .where(SmartList.account_id == str(account_id), SmartList.sync_state == DELETING)
            .order_by(SmartList.id)
        )).all()
        ids = (await s.execute(
            select(SmartList.id)
            .where(SmartList.account_id == str(account_id), SmartList.is_active.is_(True))
            .order_by(SmartList.synced_at, SmartList.id)
        )).scalars().all()
    if not ids and not tombstones:
        return {"status": "skipped", "reason": "no_active_lists"}

    import automation_executor as ax
    state = _Run(str(account_id), await asyncio.to_thread(ax._make_client, account_id))
    if refusal(state.client, "list_users_in"):
        return {"status": "skipped", "reason": f"{PLATFORM_LACKS_PREFIX}list_users_in"}
    stats: dict = {"lists": len(ids), "ok": 0, "pending": 0, "error": 0, "deleted": 0}
    for list_id, of_list_id in tombstones:
        if await _finish_tombstone(state, int(list_id), of_list_id):
            stats["deleted"] += 1
    for list_id in ids:
        row = await _claim(int(list_id))
        if row is None:
            continue
        try:
            result = await _sync_one(state, row)
        except Exception as e:  # noqa: BLE001 — one list's failure never stops the rest
            log.warning("smart_list_sync list=%s failed: %s", list_id, _short(e))
            result = {"sync_state": "error", "sync_error": _short(e)}
        await _save(int(list_id), **result)
        stats[result["sync_state"]] += 1
    stats["writes"] = _MAX_WRITES_PER_RUN - state.budget
    stats["status"] = "ok"
    return stats
