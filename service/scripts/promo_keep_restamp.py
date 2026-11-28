#!/usr/bin/env python3
"""promo_keep_restamp — the Host fence's failover step (ADR-0041, docs/spec/phase-01-promo-preempt.md).

Stamps this box's PROMO_CREATE_HOST_ID on every Kept campaign (auto_reactivate) whose
keep_host_id differs (another box's id, "", or NULL from before migration 0126), so this
box makes their automatic re-creates. Run on the box taking over, and at the deploy that
first sets the env. Idempotent: an already-stamped campaign is left alone.

Dry run by default: prints each campaign it would stamp and the count, and every Kept free
trial with no Offer limit (limit_needed). Refuses when the env is empty (a
stamp of "" fences everything).

USAGE (in the relay container, /app: its env and DB):
  python service/scripts/promo_keep_restamp.py            # dry run
  python service/scripts/promo_keep_restamp.py --apply
  python service/scripts/promo_keep_restamp.py --apply --owned-only   # a Cell half: only OI_ACCOUNTS' Creators
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

from sqlalchemy import or_, select  # noqa: E402

import cell_mode  # noqa: E402
import promo_create_guard  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import PromoCampaign  # noqa: E402


async def restamp(host: str, apply: bool, owned: frozenset[str] | None = None) -> int:
    """Stamp `host` on the Kept campaigns not carrying it; returns how many (would be)."""
    only = () if owned is None else (PromoCampaign.account_id.in_(sorted(owned)),)
    async with get_session() as s:
        rows = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.auto_reactivate.is_(True), *only,
            or_(PromoCampaign.keep_host_id.is_(None), PromoCampaign.keep_host_id != host))
            .order_by(PromoCampaign.id))).scalars().all()
        for r in rows:
            print(f"campaign={r.id} account={r.account_id} name={r.name!r} stamp={r.keep_host_id!r} -> {host!r}")
            if apply:
                r.keep_host_id = host
        for r in (await s.execute(select(PromoCampaign).where(PromoCampaign.auto_reactivate.is_(True), *only)
                                  .order_by(PromoCampaign.id))).scalars().all():
            if promo_create_guard.trial_unlimited(r):
                print(f"limit_needed campaign={r.id} account={r.account_id} name={r.name!r}: a free "
                      f"trial with no Offer limit — Keep running turns it off; set one, re-tick it")
    print(f"{'stamped' if apply else 'would stamp (dry run, --apply to write)'} {len(rows)} Kept campaign(s)")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the stamps (default: dry run)")
    ap.add_argument("--owned-only", action="store_true",
                    help="only campaigns of this Cell's OnlyFans Creators in OI_ACCOUNTS (after a carve)")
    args = ap.parse_args(argv)
    host = promo_create_guard.host_id()
    if not host:
        print(f"refused: {promo_create_guard.HOST_ENV} is empty on this box — set it first", file=sys.stderr)
        return 2
    owned = None
    if args.owned_only:
        if not os.environ.get("OI_ACCOUNTS", "").strip():
            print("refused: --owned-only needs OI_ACCOUNTS (this Cell's Creators)", file=sys.stderr)
            return 2
        owned = frozenset(a for a in cell_mode.owned_ids() if cell_mode.owned("onlyfans", a))
    asyncio.run(restamp(host, args.apply, owned))
    return 0


if __name__ == "__main__":
    sys.exit(main())
