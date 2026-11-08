"""service/vault_runs.py — the vault mirror's run rows and page writes, shared by the
"Collect all" button and Refresh (vault_ai_api) and the background collector
(vault_collect), so neither reaches into the other's privates.

  manual_running     accounts a manual Collect is sweeping right now (process-local)
  AUTO_PHASE_PREFIX  every collector run's phase starts with it
  update_run         set fields on one VaultCacheRun row
  walked_since       a whole-vault walk (or a capped one) finished since — the collector's schedule
  full_walk_done     THE "the whole vault was walked" question (`complete`)
  capped_error       the error text a page-capped walk ends done with
  latest_manual_run  the Collect button's latest run (auto:* runs excluded)
  prune_auto_runs    bound the collector's run rows per account
  upsert_page        one OF vault/media page into the mirror
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select

import vault_mirror
from db.engine import get_session
from db.models import VaultCacheRun, VaultItem
from jsonsafe import load_json

# Guard against two concurrent MANUAL sweeps for the same account clobbering each
# other. The background collector keeps its own set and stays off these.
manual_running: set[str] = set()
AUTO_PHASE_PREFIX = "auto:"
AUTO_RUNS_KEPT = 10   # newest collector rows kept per account (+ its newest walk)


async def update_run(run_id: int, **fields: Any) -> None:
    """Set `fields` on the VaultCacheRun row (if it still exists) and commit."""
    async with get_session() as s:
        run = await s.get(VaultCacheRun, run_id)
        if run:
            for k, v in fields.items():
                setattr(run, k, v)
            await s.commit()


def capped_error(max_pages: int) -> str:
    """The error a walk the page cap stopped (OF still saying hasMore) ends done with."""
    return f"walk capped at {max_pages} pages (hasMore still true)"


def _walked():
    """A finished vault walk: a manual Collect (phase "done") or a collector run that
    paged All (phase "auto:done" with pages_done > 0 — a hot-set-only refresh leaves
    0). One the page cap stopped counts too; it carries `capped_error` (a done row
    has an error only then)."""
    return (VaultCacheRun.status == "done") & or_(
        VaultCacheRun.phase == "done",
        (VaultCacheRun.phase == f"{AUTO_PHASE_PREFIX}done") & (VaultCacheRun.pages_done > 0))


async def walked_since(s: Any, account_id: str, since: datetime) -> bool:
    """The collector's weekly re-walk: a walk (capped or not) finished at/after
    `since`. Re-walking a capped vault sooner would stop at the same cap."""
    stmt = select(VaultCacheRun.id).where(
        VaultCacheRun.account_id == account_id, _walked(), VaultCacheRun.finished_at >= since)
    return (await s.execute(stmt.limit(1))).first() is not None


async def full_walk_done(s: Any, account_id: str) -> bool:
    """THE definition of "the whole vault was walked" (`cache/summary`'s `complete`):
    the account's newest walk, manual or collector, was not stopped by the page cap.
    A capped walk after an uncapped one means the vault outgrew the cap."""
    err = (await s.execute(
        select(VaultCacheRun.error).where(VaultCacheRun.account_id == account_id, _walked())
        .order_by(VaultCacheRun.finished_at.desc(), VaultCacheRun.id.desc()).limit(1))).first()
    return err is not None and err[0] is None


async def latest_manual_run(s: Any, account_id: str) -> VaultCacheRun | None:
    """The account's most recently started MANUAL collect run, or None. The
    background collector's `auto:*` runs are not the Collect button's."""
    return (
        await s.execute(
            select(VaultCacheRun)
            .where(VaultCacheRun.account_id == account_id,
                   or_(VaultCacheRun.phase.is_(None),
                       ~VaultCacheRun.phase.like(f"{AUTO_PHASE_PREFIX}%")))
            .order_by(VaultCacheRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def prune_auto_runs(s: Any, account_id: str) -> None:
    """Delete the account's collector rows past the newest AUTO_RUNS_KEPT, never its
    newest walk (`walked_since` / `full_walk_done` read it). One row per
    6 h refresh would otherwise grow forever. Caller commits."""
    auto = (VaultCacheRun.account_id == account_id) & VaultCacheRun.phase.like(f"{AUTO_PHASE_PREFIX}%")
    keep = (select(VaultCacheRun.id).where(auto)
            .order_by(VaultCacheRun.started_at.desc(), VaultCacheRun.id.desc()).limit(AUTO_RUNS_KEPT))
    walked = (select(VaultCacheRun.id).where(auto, _walked())
            .order_by(VaultCacheRun.finished_at.desc(), VaultCacheRun.id.desc()).limit(1))
    await s.execute(delete(VaultCacheRun).where(
        auto, VaultCacheRun.id.not_in(keep), VaultCacheRun.id.not_in(walked)))


async def upsert_page(account_id: str, items: list, run_id: int | None = None, *,
                      folder_id: int | None = None) -> tuple[list[tuple[dict, dict[str, Any]]], set[int]]:
    """One OF vault/media page into the mirror, one transaction: Collect's sweep, Refresh's sync and the background
    collector all write through here. Returns `(written, known)`: each (OF media, its row values) upserted, and the
    ids of those the mirror already held (one SELECT, which also serves the folder fallback below). The statement is
    `vault_mirror`'s, shared with the import ingest: one on-conflict set, so seeing a media again refreshes only the
    mirror bookkeeping, never an AI / operator / describe field. An item with NO listStates key says nothing about
    its folders: it keeps the ones the mirror knows instead of being overwritten with [], and from a folder's page
    (`folder_id`) it IS in that one."""
    written = [(m, v) for m in items if isinstance(m, dict)
               for v in (vault_mirror.row_values(account_id, m, run_id),) if v]
    if not written:
        return [], set()
    async with get_session() as s:
        prev = dict((await s.execute(
            select(VaultItem.media_id, VaultItem.of_folder_ids).where(
                VaultItem.account_id == account_id,
                VaultItem.media_id.in_([v["media_id"] for _, v in written]))
        )).all())
        for m, v in written:
            if m.get("listStates") is None:
                ids = set(load_json(prev.get(v["media_id"]), []) or [])
                if folder_id is not None:
                    ids.add(folder_id)
                v["of_folder_ids"] = json.dumps(sorted(ids, key=str))
            await s.execute(vault_mirror.upsert_stmt(v))
        await s.commit()
    return written, set(prev)
