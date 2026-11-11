"""Vault Pro's manual Collect (POST /admin/vault-ai/collect, `vault_ai_api._run_collect`): its check names and
break-it-once faults, for scenarios/2026-11-10-vault-manual-collect.py. lib/faults.py merges `register(Fault)`.

Both faults swap `vault_ai_api._run_collect` (start_collect looks it up at call time) for a stand-in built from the
product's own pieces (`_Sweep`, `_paced_call`, `vault_collect.hot_folders`, `vault_runs`, `vault_frames`): only the
order of the OF calls and of the downloads changes. A missing attribute raises (the relay fails to boot: INFRA,
never a silent no-op fault).
"""
from __future__ import annotations

NEWEST_FIRST = "collect_newest_first"
FIRST_BATCH_EARLY = "collect_first_batch_early"
COMPLETE = "collect_complete"
ONCE = "collect_once"
STATUS_P95 = "collect_status_p95"


def _need(mod, *names: str) -> None:
    for n in names:
        if not hasattr(mod, n):
            raise RuntimeError(f"slop fault: {mod.__name__}.{n} is gone; update lib/vault_manual_collect_faults.py")


def _patched(*, newest_first: bool) -> None:
    """`_run_collect` with every page's stills deferred to the end of the walk (one batch, in walk order), and,
    unless `newest_first`, the pre-2026-11-10 order: the asc walk from offset 0, no newest page, no folder pages,
    storyboards in walk (oldest-first) order."""
    import asyncio
    from datetime import datetime

    import automation_executor as ax
    import vault_ai_api as v
    import vault_collect
    import vault_frames
    import vault_runs

    _need(v, "_run_collect", "_Sweep", "_paced_call", "_PAGE", "_MAX_PAGES", "_warm_progress")
    _need(vault_collect, "hot_folders", "preempt")

    class Deferred(v._Sweep):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.later: list = []

        async def batch(self, written: list) -> None:   # count now, download after the walk
            self.later.extend(written)
            for _m, vals in written:
                self.seen.add(vals["media_id"])

        async def flush(self) -> None:
            pending, self.later, self.seen = self.later, [], set()
            await v._Sweep.batch(self, pending)

    async def run(account_id: str, run_id: int) -> None:
        try:
            await vault_collect.preempt(account_id)
            client = await asyncio.to_thread(ax._make_client, account_id)
            call = v._paced_call()
            sweep = Deferred(client, account_id, run_id)
            if newest_first:
                resp = await call(client.vault_media, limit=v._PAGE, offset=0, type="all", sort="desc")
                await sweep.page((resp or {}).get("list") or [])
                await vault_collect.hot_folders(account_id, client, call, run_id=run_id, on_page=sweep.batch)
            offset, walk_pages, more = 0, 0, True
            while walk_pages < v._MAX_PAGES:
                resp = await call(client.vault_media, limit=v._PAGE, offset=offset, type="all", sort="asc")
                items = (resp or {}).get("list") or []
                if not items:
                    break
                await sweep.page(items)
                walk_pages += 1
                offset += v._PAGE
                more = bool((resp or {}).get("hasMore"))
                if not more:
                    break
            await sweep.flush()
            vids = list(sweep.videos.values() if isinstance(sweep.videos, dict) else sweep.videos)  # walk order
            videos = sorted(vids, key=lambda x: x[0], reverse=True) if newest_first else vids
            await vault_runs.update_run(run_id, phase="warming")
            for _, vurl, vdur in videos:
                try:
                    await asyncio.to_thread(vault_frames.warm_one_sync, client, vurl, vdur)
                except Exception:  # noqa: BLE001
                    pass
            capped = vault_runs.capped_error(v._MAX_PAGES) if more and walk_pages >= v._MAX_PAGES else None
            total = len(sweep.seen)
            await vault_runs.update_run(run_id, status="done", phase="done", pages_done=sweep.pages,
                                        total_seen=total, upserted=total, error=capped,
                                        finished_at=datetime.utcnow())
        except Exception as e:  # noqa: BLE001
            await vault_runs.update_run(run_id, status="error", error=str(e)[:500], finished_at=datetime.utcnow())
        finally:
            vault_runs.manual_running.discard(account_id)
            v._warm_progress.pop(account_id, None)

    v._run_collect = run


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-10-vault-manual-collect --break (the scenario's FAULT): the pre-change sweep, asc from
        # offset 0 with every still downloaded after the whole walk.
        "manual-collect-asc-first": Fault(lambda: _patched(newest_first=False), (NEWEST_FIRST, FIRST_BATCH_EARLY)),
        # --fault=manual-collect-warm-at-end: the new OF order kept, the downloads left to the end of the walk.
        "manual-collect-warm-at-end": Fault(lambda: _patched(newest_first=True), (FIRST_BATCH_EARLY,)),
    }
