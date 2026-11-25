from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select

import vault_mirror
from db.engine import get_session
from db.models import VaultCacheRun, VaultItem
from jsonsafe import load_json

# Blocks two concurrent manual sweeps per account; the background collector keeps its own set.
manual_running: set[str] = set()
AUTO_PHASE_PREFIX = "auto:"
AUTO_RUNS_KEPT = 10
STOPPED = "stopped"
UNVERIFIED = "unverified"


async def update_run(run_id: int, **fields: Any) -> None:
    async with get_session() as s:
        run = await s.get(VaultCacheRun, run_id)
        if run:
            for k, v in fields.items():
                setattr(run, k, v)
            await s.commit()


def capped_error(max_pages: int) -> str:
    return f"walk capped at {max_pages} pages (hasMore still true)"


GAP_ERROR = ("walk not verified: OF's list shifted mid-walk (items removed), some items may be unseen; "
             "not counted as a walk, so the next scheduled walk runs again")


def _walked():
    return (VaultCacheRun.status == "done") & or_(
        VaultCacheRun.phase == "done",
        (VaultCacheRun.phase == f"{AUTO_PHASE_PREFIX}done") & (VaultCacheRun.pages_done > 0))


async def walked_since(s: Any, account_id: str, since: datetime) -> bool:
    stmt = select(VaultCacheRun.id).where(
        VaultCacheRun.account_id == account_id, _walked(), VaultCacheRun.finished_at >= since)
    return (await s.execute(stmt.limit(1))).first() is not None


async def full_walk_done(s: Any, account_id: str) -> bool:
    err = (await s.execute(
        select(VaultCacheRun.error).where(VaultCacheRun.account_id == account_id, _walked())
        .order_by(VaultCacheRun.finished_at.desc(), VaultCacheRun.id.desc()).limit(1))).first()
    return err is not None and err[0] is None


async def latest_manual_run(s: Any, account_id: str) -> VaultCacheRun | None:
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
    auto = (VaultCacheRun.account_id == account_id) & VaultCacheRun.phase.like(f"{AUTO_PHASE_PREFIX}%")
    keep = (select(VaultCacheRun.id).where(auto)
            .order_by(VaultCacheRun.started_at.desc(), VaultCacheRun.id.desc()).limit(AUTO_RUNS_KEPT))
    walked = (select(VaultCacheRun.id).where(auto, _walked())
            .order_by(VaultCacheRun.finished_at.desc(), VaultCacheRun.id.desc()).limit(1))
    await s.execute(delete(VaultCacheRun).where(
        auto, VaultCacheRun.id.not_in(keep), VaultCacheRun.id.not_in(walked)))


async def upsert_page(account_id: str, items: list, run_id: int | None = None, *,
                      folder_id: int | None = None) -> tuple[list[tuple[dict, dict[str, Any]]], set[int]]:
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
