#!/usr/bin/env python3
"""promo_reactivate automation tests — re-arm finished promos. OF is faked.

  case_dry_run_is_default        no dry_run key → plans only, zero OF calls.
  case_dry_run_null_is_still_a_dry_run
                                 a STORED `dry_run: null` too — the one
                                 non-boolean the API keeps, and this kind is
                                 uncatalogued so no seam test covers it.
  case_reactivates_finished      OF says finished → re-created, mirror repointed.
  case_rearm_preserves_a_zero_claim_cap  0 = unlimited, not "unset".
  case_skips_active              still live on OF → left alone.
  case_ignores_unmanaged         auto_reactivate off → never touched.
  case_fails_closed_when_of_down OF unreachable → stands down (no duplicate promo).
  case_respects_cycle_cap        max_reactivations reached → skipped.
  case_skips_without_discount    no saved discount → skipped (OF would reject).
  case_rearm_keeps_both_audiences  "all,expired" goes back to OF as its list.

Run: ./venv/bin/python service/tests/test_promo_reactivate.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

from datetime import datetime  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers plugins
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, LinkMeta, PromoCampaign  # noqa: E402
from sqlalchemy import select  # noqa: E402


class FakeOF:
    """OF promo endpoints, live-accurate: {items:[...]} on read, LIST on create."""
    def __init__(self):
        self._id = 80_000_000
        self.store: dict[int, dict] = {}
        self.created: list[dict] = []
        self.types: list = []

    def _item(self, pid, *, counts, days, message, finished):
        return {"id": pid, "message": message, "price": 3, "type": "all",
                "subscribeCounts": counts, "subscribeDays": days,
                "claimsCount": 0, "isFinished": finished}

    def seed(self, pid, *, finished, counts=10, days=30, message=""):
        self.store[pid] = self._item(pid, counts=counts, days=days,
                                     message=message, finished=finished)

    def promotions(self, *, offset=0, limit=100):
        # OF pages this endpoint and its hasMore is ALWAYS true, so the fake
        # mimics both: callers must stop on a short page, not on hasMore.
        page = list(self.store.values())[offset:offset + limit]
        return {"hasMore": True, "items": page}

    def create_promo(self, *, discount, subscribe_counts, subscribe_days=30, message="", type="all"):
        self.types.append(type)
        self._id += 1
        item = self._item(self._id, counts=subscribe_counts, days=subscribe_days,
                          message=message, finished=False)
        self.store[self._id] = item
        self.created.append({"discount": discount, "counts": subscribe_counts,
                             "days": subscribe_days, "message": message})
        return [item]   # LIST response


def _use_fake() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    return f


async def _seed_campaign(aid, *, of_id, auto=True, discount=50, count=0, message="Promo",
                         subscribe_counts=10, subscribe_days=30, promo_type="all"):
    async with get_session() as s:
        if not await s.get(Account, aid):
            s.add(Account(id=aid))
        row = PromoCampaign(
            account_id=aid, of_promo_id=of_id, name="Summer", discount_percent=discount,
            price_cents=0, subscribe_counts=subscribe_counts,
            subscribe_days=subscribe_days, message=message,
            promo_type=promo_type, status="active", subscriber_count=0,
            auto_reactivate=auto, reactivate_count=count, created_at=datetime.utcnow(),
        )
        s.add(row)
        await s.flush()
        return row.id


async def _campaign(cid):
    async with get_session() as s:
        return await s.get(PromoCampaign, cid)


async def case_dry_run_is_default():
    aid = "pr_dry"
    await _seed_campaign(aid, of_id=111)
    f = _use_fake(); f.seed(111, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={})
    assert res.get("dry_run") is True, res
    assert res["due"] == 1 and res["reactivated"] == 0, res
    assert f.created == [], "dry run must not create on OF"


async def case_dry_run_null_is_still_a_dry_run():
    """R3-9. `dry_run: null` is the ONE non-boolean the rules API stores — it
    skips a None value instead of rejecting it — and the old read
    `bool(payload.get("dry_run", True))` resolved it to FALSE, because `.get`
    found the key and the default never ran. That is a real re-arm on OF under a
    comment that said "# default SAFE".

    This kind has no `_CATALOG` entry, so
    `test_automation_rules_api.case_every_catalogued_bool_honours_its_default`
    will never walk it — the class check can only speak for knobs the catalog
    declares. This case is the whole coverage for this one, which is why it
    exists rather than being folded into the case above."""
    aid = "pr_dry_null"
    await _seed_campaign(aid, of_id=113)
    f = _use_fake(); f.seed(113, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": None})
    assert res.get("dry_run") is True, res
    assert res["due"] == 1 and res["reactivated"] == 0, res
    assert f.created == [], "a null dry_run must not create on OF"


async def case_reactivates_finished():
    aid = "pr_go"
    cid = await _seed_campaign(aid, of_id=222, discount=40)
    f = _use_fake(); f.seed(222, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert len(f.created) == 1 and f.created[0]["discount"] == 40, f.created
    row = await _campaign(cid)
    assert row.of_promo_id not in (None, 222), "mirror must repoint at the NEW promo"
    assert row.reactivate_count == 1 and row.status == "active", (row.reactivate_count, row.status)
    assert row.last_reactivated_at is not None
    # The finished promo stays under the campaign, so its claimers' spend still
    # counts toward the campaign's Revenue (link_metrics).
    async with get_session() as s:
        meta = (await s.execute(select(LinkMeta).where(
            LinkMeta.account_id == aid, LinkMeta.kind == "promo", LinkMeta.of_id == 222))).scalar_one()
    assert meta.campaign_id == cid, meta.campaign_id


async def case_rearm_preserves_a_zero_claim_cap():
    """0 is a VALUE on both count knobs, not "unset".

    `subscribe_counts=0` means UNLIMITED claims — promotions_api documents it
    and deliberately dropped a max(1,...) floor so the UI could reach it.
    `subscribe_days=0` is what OF itself stores for a percent discount. An
    `or`-style default reads both as missing and silently re-arms the campaign
    as "1 claim / 30 days": the operator's always-on offer becomes a one-shot
    that finishes the moment somebody takes it.
    """
    aid = "pr_zero"
    await _seed_campaign(aid, of_id=333, discount=50,
                         subscribe_counts=0, subscribe_days=0)
    f = _use_fake(); f.seed(333, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert f.created[0]["counts"] == 0, (
        f"unlimited claim cap became {f.created[0]['counts']!r} — the re-armed "
        f"promo now finishes after that many claims")
    assert f.created[0]["days"] == 0, (
        f"subscribe_days 0 became {f.created[0]['days']!r}")


async def case_skips_active():
    """A live promo is never re-created. OF runs one promo at a time, so ANY
    live promo means a discount is already on offer — stand down."""
    aid = "pr_active"
    await _seed_campaign(aid, of_id=333)
    f = _use_fake(); f.seed(333, finished=False)   # still live
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 0, res
    assert res["skipped"] == "promo_already_live", res
    assert res["live_of_promo_id"] == 333, res
    assert f.created == []


async def case_two_armed_campaigns_do_not_ping_pong():
    """The churn bug: OF only holds one live promo, so creating one FINISHES the
    other. With two armed campaigns each tick re-created whichever was finished,
    which finished the other — a real promo minted on the creator's public
    profile every tick, forever, with no fixed point."""
    aid = "pr_pingpong"
    await _seed_campaign(aid, of_id=901, message="A")
    await _seed_campaign(aid, of_id=902, message="B")
    f = _use_fake()
    f.seed(901, finished=True)          # A was superseded by B
    f.seed(902, finished=False)         # B is the live one

    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False, "cooldown_minutes": 0})
    assert res["reactivated"] == 0, res
    assert res["skipped"] == "promo_already_live", res
    assert f.created == [], "must not re-create A while B's discount is live"

    # And with NOTHING live, only ONE campaign may be re-armed per run —
    # re-arming a second would instantly finish the first.
    f.store[902]["isFinished"] = True
    res2 = await run_once(aid, "promo_reactivate", payload={"dry_run": False, "cooldown_minutes": 0})
    assert res2["due"] == 2, res2
    assert res2["reactivated"] == 1, res2
    assert res2["deferred"] == 1, res2
    assert len(f.created) == 1, f.created


async def case_spent_promo_with_stale_isfinished_is_rearmed():
    """OF does not reliably flip isFinished on a spent promo — Ava has 9 with
    isFinished=False and canClaim=False, the oldest dead since 2025-12. Trusting
    isFinished alone would (a) show them as live in the UI and (b) make the
    automation stand down forever on an account with no offer running."""
    aid = "pr_stale"
    cid = await _seed_campaign(aid, of_id=808, discount=25)
    f = _use_fake()
    f.seed(808, finished=False)
    f.store[808]["canClaim"] = False          # spent, but OF never flipped isFinished

    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res.get("skipped") != "promo_already_live", f"a spent promo is not an offer: {res}"
    assert res["reactivated"] == 1, res
    row = await _campaign(cid)
    assert row.of_promo_id not in (None, 808), "mirror must repoint at the new promo"


async def case_finds_promo_beyond_page_one():
    """/promotions is paged (10 by default) and its hasMore is always true. When
    we read only page 1, an older-but-LIVE promo looked absent, i.e. "expired",
    i.e. got re-created — minting a duplicate discount."""
    aid = "pr_paged"
    await _seed_campaign(aid, of_id=999)
    f = _use_fake()
    # 250 newer promos bury ours well past the first page.
    for pid in range(1000, 1250):
        f.seed(pid, finished=True)
    f.seed(999, finished=False)        # ours is LIVE, just old
    assert list(f.store).index(999) > 100, "fixture must bury it past page 1"

    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 0, res
    assert f.created == [], "a live promo on a later page must not be re-created"


async def case_ignores_unmanaged():
    aid = "pr_off"
    await _seed_campaign(aid, of_id=444, auto=False)
    f = _use_fake(); f.seed(444, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["managed"] == 0 and res["reactivated"] == 0, res
    assert f.created == []


async def case_fails_closed_when_of_down():
    aid = "pr_down"
    await _seed_campaign(aid, of_id=555)

    class Boom:
        def promotions(self, *, offset=0, limit=100):
            raise RuntimeError("no session")
        def create_promo(self, **kw):
            raise AssertionError("must NOT create when OF is unreachable")
    ax._make_client = lambda account_id: Boom()  # type: ignore[attr-defined]
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["skipped"] == "of_unreachable" and res["reactivated"] == 0, res


async def case_respects_cycle_cap():
    aid = "pr_cap"
    await _seed_campaign(aid, of_id=666, count=3)
    f = _use_fake(); f.seed(666, finished=True)
    res = await run_once(aid, "promo_reactivate",
                         payload={"dry_run": False, "max_reactivations": 3})
    assert res["reactivated"] == 0 and res["skipped_cap"] == 1, res
    assert f.created == []


async def case_skips_without_discount():
    aid = "pr_nodisc"
    await _seed_campaign(aid, of_id=777, discount=0)
    f = _use_fake(); f.seed(777, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 0 and res["skipped_no_discount"] == 1, res
    assert f.created == []


async def case_fails_closed_without_of_id():
    """A campaign whose of_promo_id was never captured can't be looked up on OF,
    so its promo may well be LIVE. Re-creating it blind would mint a duplicate
    promo every cycle — and since the new id may not be captured either, it
    would never converge. Must skip, not re-create."""
    aid = "pr_noid"
    await _seed_campaign(aid, of_id=None)
    f = _use_fake()          # OF reachable, but this campaign isn't in it
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["due"] == 0, res
    assert res["skipped_unverifiable"] == 1, res
    assert res["reactivated"] == 0, res
    assert f.created == [], "must not create a promo it cannot verify"


async def case_rearm_keeps_both_audiences():
    """A campaign for new AND expired subscribers is stored as "all,expired";
    the re-arm must send OF's list, not that joined string (OF would 400 it),
    and a single audience stays the bare string."""
    aid = "pr_both"
    await _seed_campaign(aid, of_id=777, promo_type="all,expired")
    f = _use_fake(); f.seed(777, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert f.types == [["all", "expired"]], f.types

    aid = "pr_expired_only"
    await _seed_campaign(aid, of_id=778, promo_type="expired")
    f = _use_fake(); f.seed(778, finished=True)
    res = await run_once(aid, "promo_reactivate", payload={"dry_run": False})
    assert res["reactivated"] == 1, res
    assert f.types == ["expired"], f.types


_harness.run(
    case_rearm_keeps_both_audiences,
    case_dry_run_is_default,
    case_dry_run_null_is_still_a_dry_run,
    case_reactivates_finished,
    case_rearm_preserves_a_zero_claim_cap,
    case_skips_active,
    case_ignores_unmanaged,
    case_fails_closed_when_of_down,
    case_respects_cycle_cap,
    case_skips_without_discount,
    case_fails_closed_without_of_id,
    case_two_armed_campaigns_do_not_ping_pong,
    case_spent_promo_with_stale_isfinished_is_rearmed,
    case_finds_promo_beyond_page_one,
)
