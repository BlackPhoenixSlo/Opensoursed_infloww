#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, PromoCampaign  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "promo_keep_restamp", _harness._SERVICE / "scripts" / "promo_keep_restamp.py")
restamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(restamp)

BOX = "box-b"


async def _seed() -> dict[str, int]:
    ids = {}
    async with get_session() as s:
        for key, auto, stamp in (("other", True, "box-a"), ("pre0126", True, None), ("empty", True, ""),
                                 ("mine", True, BOX), ("unticked", False, "box-a")):
            s.add(Account(id=f"rs-{key}"))
            await s.flush()
            row = PromoCampaign(account_id=f"rs-{key}", of_promo_id=None, name=key, discount_percent=50,
                                price_cents=0, subscribe_counts=10, subscribe_days=30, message="",
                                promo_type="all", status="active", subscriber_count=0,
                                auto_reactivate=auto, reactivate_count=0, created_at=datetime.utcnow(),
                                keep_host_id=stamp)
            s.add(row)
            await s.flush()
            ids[key] = row.id
    return ids


async def _stamps() -> dict[str, str | None]:
    async with get_session() as s:
        return {r.name: r.keep_host_id for r in (await s.execute(
            PromoCampaign.__table__.select().where(PromoCampaign.account_id.like("rs-%")))).all()}


def _main(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = restamp.main(list(argv))
    return code, out.getvalue()


SEEDED = {"other": "box-a", "pre0126": None, "empty": "", "mine": BOX, "unticked": "box-a"}


def case_refuses_empty_env():
    asyncio.run(_seed())
    os.environ["PROMO_CREATE_HOST_ID"] = "  "
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code, out = _main("--apply")
    assert code == 2 and "empty" in err.getvalue() and out == "", (code, out, err.getvalue())
    assert asyncio.run(_stamps()) == SEEDED


def case_dry_run_then_apply():
    os.environ["PROMO_CREATE_HOST_ID"] = BOX
    code, out = _main()
    assert code == 0 and "would stamp" in out and out.rstrip().endswith("3 Kept campaign(s)"), out
    assert all(f"name={k!r}" in out for k in ("other", "pre0126", "empty")), out
    assert "name='mine'" not in out and "name='unticked'" not in out, out
    assert asyncio.run(_stamps()) == SEEDED, "a dry run writes nothing"
    code, out = _main("--apply")
    assert code == 0 and out.rstrip().endswith("stamped 3 Kept campaign(s)"), out
    assert asyncio.run(_stamps()) == {**SEEDED, "other": BOX, "pre0126": BOX, "empty": BOX}
    code, out = _main("--apply")
    assert code == 0 and out.rstrip().endswith("stamped 0 Kept campaign(s)"), out


def case_rv_r1_restamp_reports_unlimited_trials():
    async def seed():
        async with get_session() as s:
            s.add(Account(id="rs-trial"))
            await s.flush()
            s.add(Account(id="rs-capped"))
            await s.flush()
            for aid, name, cap in (("rs-trial", "trial", 0), ("rs-capped", "capped", 5)):
                s.add(PromoCampaign(account_id=aid, of_promo_id=7, name=name, discount_percent=100,
                                    price_cents=0, subscribe_counts=cap, subscribe_days=3, message="",
                                    promo_type="all", status="active", subscriber_count=0,
                                    auto_reactivate=True, reactivate_count=0, created_at=datetime.utcnow(),
                                    keep_host_id=BOX, recreates_left=None))
    asyncio.run(seed())
    os.environ["PROMO_CREATE_HOST_ID"] = BOX
    code, out = _main()
    assert code == 0 and "limit_needed" in out and "name='trial'" in out, out
    assert "name='capped'" not in out, out


_harness.run(case_refuses_empty_env, case_dry_run_then_apply, case_rv_r1_restamp_reports_unlimited_trials)
