from __future__ import annotations

from datetime import datetime, timedelta

from _kind_verdict_seeds import HOST, _rows, _rule
from db.engine import get_session
from db.models import PromoCampaign, PromoKeepState

VERDICTS = {
    "fansly": {"promo_reactivate": {"run": "gated:platform_lacks:promotions",
                                    "recheck": "gated:platform_lacks:promotions"}},
    "onlyfans": {"promo_reactivate": {"run": "same", "recheck": "same"}},
}

PAYLOADS = {"promo_reactivate": {"run": {"dry_run": False}, "recheck": {"dry_run": False, "_recheck": "expiry"}}}

SAME_EFFECTS = {"onlyfans": {"promo_reactivate": {
    "run": ("create_promo", "job:promo_reactivate", "table:link_meta", "table:promo_campaigns",
            "table:promo_create_reservations", "table:promo_keep_state"),
    "recheck": ("create_promo", "job:promo_reactivate", "table:link_meta", "table:promo_campaigns",
                "table:promo_create_reservations", "table:promo_keep_state"),
}}}


def _campaign(aid, _platform):
    return PromoCampaign(account_id=aid, of_promo_id=7701, name="keep", discount_percent=50, subscribe_counts=10,
                         subscribe_days=30, auto_reactivate=True, keep_host_id=HOST, keep_ticked_at=datetime.utcnow())


_KEEP = _rows(_rule("promo_reactivate", dry_run=False), _campaign)


async def own_recheck_slot(aid: str, job_id: int) -> None:
    async with get_session() as s:
        s.add(PromoKeepState(account_id=aid, recheck_job_id=job_id,
                             recheck_at=datetime.utcnow() - timedelta(seconds=5)))


SEEDS = {("promo_reactivate", "run"): _KEEP, ("promo_reactivate", "recheck"): _KEEP}

JOB_SEEDS = {("promo_reactivate", "recheck"): own_recheck_slot}
