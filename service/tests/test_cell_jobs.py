from __future__ import annotations

import _harness

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select  # noqa: E402

_harness.bootstrap()

OWNED, STRAY = "900539700124344320", "900539700124344321"
_placement = Path(tempfile.mkdtemp()) / "placement.json"
_placement.write_text(json.dumps({
    "schema": 1, "agency": "acme", "generation": 1, "written_at": "2026-11-26T10:00:00Z", "by": "fleet.py",
    "min_cell_proto": 1,
    "cells": {"s02": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:1", "role": "data", "state": "live"},
              "s03": {"box": "b1", "epoch": 1, "relay": "127.0.0.1:2", "role": "data", "state": "live"}},
    "accounts": {f"onlyfans:{OWNED}": "s02", f"onlyfans:{STRAY}": "s03"}}))
os.environ.update({"OI_CELL_MAP": str(_placement), "OI_CELL_ID": "s02", "OI_CELL_ROLE": "data",
                   "OI_ACCOUNTS": f"onlyfans:{OWNED}", "OI_EPOCH": "1"})

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
from automation_registry import register  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRule, ScheduledJob  # noqa: E402

_harness.make_client()
import server  # noqa: E402

account_registry.list_accounts = lambda include_watchers=False: [
    {"id": a, "has_session": True} for a in (OWNED, STRAY)]
STARTED: list[str] = []
server._start_account_pump = STARTED.append


@register("t_cell_noop")
async def _t_noop(account_id: str, payload: dict, *, run_id: int) -> dict:
    return {}


async def _seed() -> None:
    async with get_session() as s:
        for aid in (OWNED, STRAY):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))


async def case_pump_supervisor_starts_only_owned() -> None:
    STARTED.clear()
    await server._reconcile_pumps()
    assert STARTED == [OWNED], STARTED


def case_direct_pump_start_refuses_stray() -> None:
    server._do_start_account_pump(STRAY)
    assert STRAY not in server._account_pumps, "a pump task exists for a Creator this Cell does not own"


async def case_due_jobs_list_only_owned() -> None:
    await _seed()
    now = datetime.utcnow()
    async with get_session() as s:
        for aid in (OWNED, STRAY):
            s.add(ScheduledJob(account_id=aid, kind="t_cell_noop", payload_json="{}",
                               status="pending", run_at=now - timedelta(seconds=5)))
    pairs = {(a, k) for a, k, *_ in await ax._due_job_pairs()}
    assert (OWNED, "t_cell_noop") in pairs and (STRAY, "t_cell_noop") not in pairs, pairs


async def case_rules_materialize_only_owned() -> None:
    await _seed()
    async with get_session() as s:
        for aid in (OWNED, STRAY):
            s.add(AutomationRule(account_id=aid, name="scrape", kind="scrape_chats",
                                 trigger_json=json.dumps({"every_seconds": 1}),
                                 steps_json=json.dumps({"chat_ids": [5555]}), is_enabled=True))
    await ax._materialize_due_rules()
    async with get_session() as s:
        got = set((await s.execute(select(ScheduledJob.account_id).where(
            ScheduledJob.kind == "scrape_chats"))).scalars().all())
    assert got == {OWNED}, got


async def case_dead_session_probe_skips_stray() -> None:
    probed: list[str] = []
    real = ax._make_client
    ax._make_client = lambda aid: probed.append(aid) or (_ for _ in ()).throw(RuntimeError("no OF here"))
    try:
        for aid in (OWNED, STRAY):
            await account_health.mark_session_dead(aid, "wrong_user")
        await ax._probe_dead_sessions()
    finally:
        ax._make_client = real
    assert probed == [OWNED], probed


_harness.run()
