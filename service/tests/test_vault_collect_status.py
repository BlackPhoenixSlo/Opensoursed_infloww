#!/usr/bin/env python3
"""GET /admin/vault-ai/collect/status names the store being warmed.

REGRESSION (wave6 B12): `_run_collect` writes `phase="thumbs"` on the run row once
before warming three stores (thumbs, images, posters), so the status route said
"thumbs" while the full-frame store warmed and the counter visibly reset. The
live warm phase now wins while a warm is in flight; the row's phase otherwise.

Run: ./venv/bin/python service/tests/test_vault_collect_status.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
_harness.bootstrap()

from datetime import datetime  # noqa: E402

import vault_ai_api as api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultCacheRun  # noqa: E402

AID = "acc_collect_status"


async def _seed_run() -> None:
    async with get_session() as s:
        s.add(Account(id=AID))
    async with get_session() as s:
        s.add(VaultCacheRun(account_id=AID, status="running", phase="thumbs",
                            started_at=datetime.utcnow()))


async def case_status_reports_the_store_being_warmed():
    api.assert_account_owned = lambda _aid: None
    await _seed_run()
    api._warm_progress[AID] = {"phase": "images", "warmed": 10, "warm_total": 711}
    try:
        run = (await api.collect_status(account_id=AID))["run"]
    finally:
        api._warm_progress.pop(AID, None)
    assert run["phase"] == "images", run
    assert (run["warmed"], run["warm_total"]) == (10, 711), run

    # No warm in flight → the row's own phase.
    run = (await api.collect_status(account_id=AID))["run"]
    assert run["phase"] == "thumbs", run


_harness.run(case_status_reports_the_store_being_warmed)
