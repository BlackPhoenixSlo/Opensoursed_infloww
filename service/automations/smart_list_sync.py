from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from datetime import datetime

from sqlalchemy import delete, or_, select, update

import platforms
from audience_include import _crawl_list_ids_blocking
from automation_registry import register
from db.engine import get_session
from db.models import SmartList
from of_client import OFAPIError
from of_paging import ListGone, list_audience
from side_effect_gate import PLATFORM_LACKS_PREFIX, delete_list_checked, delete_list_refusal, delete_list_ungranted
from smart_list_rules import requires_active_subscription, rules_refusal

log = logging.getLogger("of-relay.automation.smart_list_sync")

_KIND = "smart_list_sync"
_SEND_PURPOSE = "not_fan_dm"
# Leftover waits for the next run, which also bounds how fast a wrong target could empty a list.
_MAX_WRITES_PER_RUN = 40  # ≈7.5 min of paced writes per run, all lists together
_ADD_CHUNK = 100
_MAX_MEMBERS = 19_000  # under the 20k crawl backstop
_ROSTER_USABLE = ("crawled", "fresh")
SYNC_METHODS = ("list_users_in", "add_users_to_lists", "remove_user_from_list", "create_list")


def sync_refusal(account_id: str) -> str | None:
    for name in SYNC_METHODS:
        if platforms.refusal_for_account(account_id, name):
            return f"{PLATFORM_LACKS_PREFIX}{name}"
    return None


def _not_found(e: Exception) -> bool:
    return isinstance(e, ListGone) or (isinstance(e, OFAPIError) and
                                         getattr(e.response, "status_code", None) == 404)


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
        self.platform = platforms.for_account(account_id)
        self.budget = _MAX_WRITES_PER_RUN
        self.roster: str | None = None

    async def write(self, fn):
        self.budget -= 1
        return await _write(self.account_id, fn)


@dataclass
class _Tally:
    left: int
    added: int = 0
    unconfirmed: int = 0
    removed: int = 0
    failed: int = 0


async def _add(run: _Run, row: SmartList, of_list_id: int, chunk: list[int], t: _Tally) -> bool:
    if run.budget <= 0:
        return False
    t.left -= len(chunk)
    try:
        resp = await run.write(lambda: run.client.add_users_to_lists({str(of_list_id): chunk}))
    except Exception as e:  # noqa: BLE001 — retried next run
        t.failed += len(chunk)
        log.warning("smart_list_sync add failed list=%s (%s)", row.id, _short(e))
        return True
    ok = _confirmed(resp, of_list_id, chunk)
    t.added += len(ok)
    t.unconfirmed += len(chunk) - len(ok)
    return True


async def _remove(run: _Run, row: SmartList, of_list_id: int, fid: int, t: _Tally, *,
                  gone_is_removed: bool) -> bool:
    if run.budget <= 0:
        return False
    t.left -= 1
    try:
        await run.write(lambda: run.client.remove_user_from_list(of_list_id, fid))
        t.removed += 1
    except Exception as e:  # noqa: BLE001 — retried next run
        if gone_is_removed and _not_found(e):
            t.removed += 1
            return True
        t.failed += 1
        log.warning("smart_list_sync remove failed list=%s fan=%s (%s)", row.id, fid, _short(e))
    return True


async def _sync_one(run: _Run, row: SmartList) -> tuple[dict, int]:
    from smart_lists_api import (
        _load_normalised_fans, _rules_of, resolve, uses_subscription_facts,
    )
    from automations.lifecycle_messages import last_crawl_was_empty, refresh_roster

    rules = _rules_of(row)
    needs_roster = uses_subscription_facts(rules)
    if needs_roster:
        if run.roster is None:
            res = await refresh_roster(run.account_id, run.client, now=datetime.utcnow())
            run.roster = str(res.get("roster"))
        if run.roster not in _ROSTER_USABLE:
            return {"sync_state": "error",
                    "sync_error": f"subscriber roster unavailable ({run.roster}) — nothing synced"}, 0
    fans = await _load_normalised_fans(run.account_id, rules,
                                       roster_fresh=run.roster in _ROSTER_USABLE)
    target = set(resolve(rules, fans))
    bounded = run.platform.list_member_limit
    cap = bounded if bounded is not None else _MAX_MEMBERS
    if len(target) > cap:
        return {"sync_state": "error",
                "sync_error": f"{len(target)} fans match — lists above {cap} are not synced"}, 0

    of_list_id = row.of_list_id
    if of_list_id is None:
        if run.budget <= 0:
            return {"sync_state": "pending", "sync_error": None}, 0
        created = await run.write(lambda: run.client.create_list(row.name))
        new_id = created.get("id") if isinstance(created, dict) else None
        if not new_id:
            return {"sync_state": "error", "sync_error": "Upstream did not return a list id"}, 0
        of_list_id = int(new_id)
        # Persist at once: the next run must find it, never create a second list.
        await _save(row.id, of_list_id=of_list_id, of_list_name=row.name)
        row.of_list_name = row.name

    try:
        members, truncated = await asyncio.to_thread(
            _crawl_list_ids_blocking, run.client, of_list_id, list_page=run.platform.list_page)
    except Exception as e:
        if _not_found(e):
            return {"sync_state": "error", "of_list_id": None, "of_list_name": None,
                    "member_count": None,
                    "sync_error": "the upstream list was deleted — a new one is "
                                  "created on the next sync"}, 0
        raise
    if truncated:
        error = f"List crawl incomplete ({cap}-member cap) — nothing synced"
        return {"sync_state": "error", "sync_error": error}, 0
    # Rename only after the crawl has shown the list still exists on OF.
    if row.of_list_name != row.name and run.budget > 0:
        await run.write(lambda: run.client.rename_list(of_list_id, row.name))
        await _save(row.id, of_list_name=row.name)

    adds = sorted(target - members)
    removes = sorted(members - target)
    if removes and not fans:
        if not (run.platform.confirms_empty_active_roster and requires_active_subscription(rules)
                and await last_crawl_was_empty(run.account_id)):
            return {"sync_state": "error",
                    "sync_error": "no fans stored for this creator — removals held"}, 0

    t = _Tally(left=len(adds) + len(removes))
    if bounded is not None:
        for fid in removes:
            if not await _remove(run, row, of_list_id, fid, t, gone_is_removed=False):
                break
        room = cap - (len(members) - t.removed)
        for fid in adds[:max(room, 0)]:
            if not await _add(run, row, of_list_id, [fid], t):
                break
    else:
        for i in range(0, len(adds), _ADD_CHUNK):
            if not await _add(run, row, of_list_id, adds[i:i + _ADD_CHUNK], t):
                break
        for fid in removes:
            if not await _remove(run, row, of_list_id, fid, t, gone_is_removed=True):
                break

    notes = []
    if t.unconfirmed:
        notes.append(f"{t.unconfirmed} fans could not be added")
    if t.failed:
        notes.append(f"{t.failed} list writes failed — retried next sync")
    log.info("smart_list_sync list=%s of_list=%s target=%d members=%d +%d -%d left=%d",
             row.id, of_list_id, len(target), len(members), t.added, t.removed, t.left)
    unconfirmed = t.unconfirmed if run.platform.retry_unconfirmed_list_adds else 0
    return {"sync_state": "pending" if (t.left or t.failed or unconfirmed) else "ok",
            "sync_error": "; ".join(notes) or None,
            "synced_at": datetime.utcnow(),
            "member_count": len(members) + t.added - t.removed}, unconfirmed


async def _finish_tombstone(run: _Run, list_id: int, of_list_id: int | None, held: dict[int, str]) -> bool:
    if of_list_id is not None:
        if run.budget <= 0:
            return False
        read_members = partial(list_audience, run.client, of_list_id, list_page=run.platform.list_page)
        try:
            args = (run.account_id, of_list_id, run.client, read_members)
            why = await asyncio.to_thread(delete_list_refusal, *args)
            if why is None:
                why = await run.write(partial(delete_list_checked, *args))
            if why is not None:
                held[list_id] = why
                return False
        except Exception as e:  # noqa: BLE001 — the tombstone retries next run
            if not _not_found(e):
                log.warning("smart_list_sync delete of list %s failed (%s)", of_list_id, _short(e))
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
    from smart_lists_api import DELETING, _rules_of
    if reason := sync_refusal(str(account_id)):
        return {"status": "skipped", "reason": reason}
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
        rows = (await s.execute(
            select(SmartList.id, SmartList.rules_json)
            .where(SmartList.account_id == str(account_id), SmartList.is_active.is_(True))
            .order_by(SmartList.synced_at, SmartList.id)
        )).all()
    platform = platforms.for_account(str(account_id))
    refused = {int(r.id): why for r in rows if (why := rules_refusal(platform, _rules_of(r)))}
    ids = [int(r.id) for r in rows if int(r.id) not in refused]
    held = {int(t): why for t, o in tombstones
            if o is not None and (why := delete_list_ungranted(str(account_id), o))}
    tombstones = [(t, o) for t, o in tombstones if int(t) not in held]
    if not ids and not tombstones:
        return {"status": "skipped",
                "reason": next(iter({**refused, **held}.values()), "no_active_lists")}

    import automation_executor as ax
    state = _Run(str(account_id), await asyncio.to_thread(ax._make_client, account_id))
    stats: dict = {"lists": len(rows), "ok": 0, "pending": 0, "error": 0, "deleted": 0}
    for list_id, of_list_id in tombstones:
        if await _finish_tombstone(state, int(list_id), of_list_id, held):
            stats["deleted"] += 1
    unconfirmed = 0
    for list_id in ids:
        row = await _claim(list_id)
        if row is None:
            continue
        try:
            result, count = await _sync_one(state, row)
            unconfirmed += count
        except Exception as e:  # noqa: BLE001 — one list's failure never stops the rest
            log.warning("smart_list_sync list=%s failed: %s", list_id, _short(e))
            result = {"sync_state": "error", "sync_error": _short(e)}
        await _save(list_id, **result)
        stats[result["sync_state"]] += 1
    stats["writes"] = _MAX_WRITES_PER_RUN - state.budget
    stats["status"] = "partial" if unconfirmed else "ok"
    if stops := {**refused, **held}:
        reason = next(iter(stops.values()))
        if any(stats[key] for key in ("ok", "pending", "error", "deleted")):
            stats.update(status="partial", reason=f"partial:{reason}")
        else:
            stats.update(status="skipped", reason=reason)
    if refused:
        stats["refused_rows"] = sorted(refused)
    if held:
        stats["held_tombstones"] = sorted(held)
    return stats
