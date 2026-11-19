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
  case_cap_reached_is_rearmed    claims >= cap is ended even with canClaim true.
  case_near_cap_queues_one_recheck  one claim short → ONE re-check in ~90 s,
                                 never two pending, never from a re-check run.
  case_expiring_soon_queues_an_expiry_recheck  expires_at before the next
                                 backstop → a re-check at expires_at + 30 s.
  case_expiry_past_but_of_live_retries_bounded  OF wins over our expires_at:
                                 no create, +60 s re-checks, at most 3.
  case_cooldown_queues_a_recheck_and_never_mints  held by the cooldown → no
                                 create, a re-check just past it (default 2 min).
  case_rearm_sends_finish_days_and_refreshes_expires_at  the bug: finish_days
                                 was dropped on re-create.
  case_dry_run_and_rule_off_queue_no_recheck  dry run never queues one; a rule
                                 switched off drops it.
  case_deleted_campaign_stops_rearming  no mirror row → nothing re-armed.

Run: ./venv/bin/python service/tests/test_promo_reactivate.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers plugins
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
import automations.promo_reactivate as pr  # noqa: E402
from db.models import Account, AutomationRule, LinkMeta, PromoCampaign, ScheduledJob  # noqa: E402
from sqlalchemy import select  # noqa: E402


class FakeOF:
    """OF promo endpoints, live-accurate: {items:[...]} on read, LIST on create."""
    def __init__(self):
        self._id = 80_000_000
        self.store: dict[int, dict] = {}
        self.created: list[dict] = []
        self.types: list = []

    def _item(self, pid, *, counts, days, message, finished, claims=0, finished_at=None):
        return {"id": pid, "message": message, "price": 3, "type": "all",
                "subscribeCounts": counts, "subscribeDays": days,
                "claimsCount": claims, "isFinished": finished, "finishedAt": finished_at}

    def seed(self, pid, *, finished, counts=10, days=30, message="", claims=0):
        self.store[pid] = self._item(pid, counts=counts, days=days,
                                     message=message, finished=finished, claims=claims)

    def promotions(self, *, offset=0, limit=100):
        # OF pages this endpoint and its hasMore is ALWAYS true, so the fake
        # mimics both: callers must stop on a short page, not on hasMore.
        page = list(self.store.values())[offset:offset + limit]
        return {"hasMore": True, "items": page}

    finished_at = None   # what OF echoes as finishedAt on create (null for most)

    def create_promo(self, *, discount, subscribe_counts, subscribe_days=30, message="", type="all",
                     **kw):
        self.types.append(type)
        self._id += 1
        item = self._item(self._id, counts=subscribe_counts, days=subscribe_days,
                          message=message, finished=False, finished_at=self.finished_at)
        self.store[self._id] = item
        self.created.append({"discount": discount, "counts": subscribe_counts,
                             "days": subscribe_days, "message": message, **kw})
        return [item]   # LIST response


def _use_fake() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    return f


async def _seed_campaign(aid, *, of_id, auto=True, discount=50, count=0, message="Promo",
                         subscribe_counts=10, subscribe_days=30, promo_type="all",
                         finish_days=None, expires_at=None, last_reactivated_at=None):
    async with get_session() as s:
        if not await s.get(Account, aid):
            s.add(Account(id=aid))
        row = PromoCampaign(
            account_id=aid, of_promo_id=of_id, name="Summer", discount_percent=discount,
            price_cents=0, subscribe_counts=subscribe_counts,
            subscribe_days=subscribe_days, message=message,
            promo_type=promo_type, status="active", subscriber_count=0,
            auto_reactivate=auto, reactivate_count=count, created_at=datetime.utcnow(),
            finish_days=finish_days, expires_at=expires_at, last_reactivated_at=last_reactivated_at,
        )
        s.add(row)
        await s.flush()
        return row.id


async def _campaign(cid):
    async with get_session() as s:
        return await s.get(PromoCampaign, cid)


async def _rechecks(aid) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == "promo_reactivate",
            ScheduledJob.status == "pending").order_by(ScheduledJob.id))).scalars())


def _near(a: datetime, b: datetime, slack_s: float = 5) -> bool:
    return abs((a - b).total_seconds()) <= slack_s


GO = {"dry_run": False}


async def _rule(aid, *, every=3600, enabled=True) -> int:
    async with get_session() as s:
        rule = AutomationRule(account_id=aid, name="keep", kind="promo_reactivate",
                              is_enabled=enabled, trigger_json=json.dumps({"every_seconds": every}),
                              steps_json=json.dumps(GO))
        s.add(rule)
        await s.flush()
        return rule.id


async def _run_rule_job(aid, rid) -> dict:
    """The rule's own job, claimed by run_once (so the run is bound to the rule)."""
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="promo_reactivate", payload_json=json.dumps(GO),
                           run_at=datetime.utcnow() - timedelta(seconds=1), status="pending",
                           rule_id=rid))
    return await run_once(aid, "promo_reactivate")


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


async def case_cap_reached_is_rearmed():
    """OF can lag flipping canClaim on a filled cap: claims >= cap is ended
    (of_promos.normalise_of_promo), so the next promo goes up now."""
    aid = "pr_capfull"
    await _seed_campaign(aid, of_id=1201, subscribe_counts=10)
    f = _use_fake(); f.seed(1201, finished=False, counts=10, claims=10)
    f.store[1201]["canClaim"] = True
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1, res
    # ... and an unlimited cap (0) is never "filled"
    aid = "pr_capzero"
    await _seed_campaign(aid, of_id=1202, subscribe_counts=0)
    f = _use_fake(); f.seed(1202, finished=False, counts=0, claims=500)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live" and f.created == [], res


async def case_near_cap_queues_one_recheck():
    aid = "pr_nearcap"
    await _seed_campaign(aid, of_id=1301, subscribe_counts=10)
    f = _use_fake(); f.seed(1301, finished=False, counts=10, claims=9)
    t0 = datetime.utcnow()
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["skipped"] == "promo_already_live" and f.created == [], res
    assert res["recheck"]["reason"] == "near_cap", res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and _near(jobs[0].run_at, t0 + timedelta(seconds=90)), jobs
    body = json.loads(jobs[0].payload_json)
    assert body["_recheck"] == "near_cap" and body["dry_run"] is False, body
    # never stacks: a second run while it is pending queues nothing
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and len(await _rechecks(aid)) == 1, res
    # a re-check run never queues another near_cap
    async with get_session() as s:
        (await s.get(ScheduledJob, jobs[0].id)).status = "done"
    res = await run_once(aid, "promo_reactivate", payload={**GO, "_recheck": "near_cap"})
    assert "recheck" not in res and await _rechecks(aid) == [], res
    # two short is not near the cap
    aid = "pr_nearcap2"
    await _seed_campaign(aid, of_id=1302, subscribe_counts=10)
    f = _use_fake(); f.seed(1302, finished=False, counts=10, claims=8)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and await _rechecks(aid) == [], res


async def case_expiring_soon_queues_an_expiry_recheck():
    aid = "pr_expsoon"
    exp = datetime.utcnow() + timedelta(minutes=10)
    await _seed_campaign(aid, of_id=1401, expires_at=exp)
    f = _use_fake(); f.seed(1401, finished=False)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["recheck"]["reason"] == "expiry" and f.created == [], res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and _near(jobs[0].run_at, exp + timedelta(seconds=30), 1), jobs
    # past the next backstop (hourly with no rule): nothing yet, the backstop has it
    aid = "pr_explater"
    await _seed_campaign(aid, of_id=1402, expires_at=datetime.utcnow() + timedelta(hours=2))
    f = _use_fake(); f.seed(1402, finished=False)
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and await _rechecks(aid) == [], res
    # the rule's own cadence is the horizon: a 3-hour rule reaches it
    rid = await _rule(aid, every=3 * 3600)
    res = await _run_rule_job(aid, rid)
    assert res["recheck"]["reason"] == "expiry", res
    jobs = await _rechecks(aid)
    assert len(jobs) == 1 and jobs[0].rule_id == rid, jobs
    assert json.loads(jobs[0].payload_json).get("_followup") is True, jobs[0].payload_json


async def case_expiry_past_but_of_live_retries_bounded():
    """Our expires_at is often a guess (created + finish_days). OF saying the
    promo is still on offer wins: no create, +60 s, at most 3 retries."""
    aid = "pr_expwrong"
    await _seed_campaign(aid, of_id=1501, expires_at=datetime.utcnow() - timedelta(seconds=40))
    f = _use_fake(); f.seed(1501, finished=False)
    retries = []
    for done in range(4):
        t0 = datetime.utcnow()
        res = await run_once(aid, "promo_reactivate",
                             payload={**GO, "_recheck": "expiry", "_expiry_retries": done})
        assert res["skipped"] == "promo_already_live", res
        jobs = await _rechecks(aid)
        if jobs:
            assert len(jobs) == 1 and _near(jobs[0].run_at, t0 + timedelta(seconds=60)), jobs
            retries.append(json.loads(jobs[0].payload_json)["_expiry_retries"])
            async with get_session() as s:
                (await s.get(ScheduledJob, jobs[0].id)).status = "done"
    assert retries == [1, 2, 3], retries
    assert f.created == [], "re-created while OF said the promo was on offer"
    # a backstop run past the guess starts no retry chain
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and await _rechecks(aid) == [], res


async def case_cooldown_queues_a_recheck_and_never_mints():
    aid = "pr_cool"
    last = datetime.utcnow() - timedelta(seconds=60)
    await _seed_campaign(aid, of_id=1601, last_reactivated_at=last)
    f = _use_fake(); f.seed(1601, finished=True)
    res = await run_once(aid, "promo_reactivate", payload=GO)   # default cooldown: 2 min
    assert res["skipped_cooldown"] == 1 and res["reactivated"] == 0 and f.created == [], res
    jobs = await _rechecks(aid)
    want = last + timedelta(minutes=2, seconds=5)
    assert len(jobs) == 1 and _near(jobs[0].run_at, want, 1), (jobs, want)
    assert json.loads(jobs[0].payload_json)["_recheck"] == "cooldown"
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert "recheck" not in res and len(await _rechecks(aid)) == 1, res
    # past the cooldown it re-arms
    async with get_session() as s:
        (await s.get(ScheduledJob, jobs[0].id)).status = "done"
    res = await run_once(aid, "promo_reactivate",
                         payload={**GO, "_recheck": "cooldown", "cooldown_minutes": 1})
    assert res["reactivated"] == 1 and len(f.created) == 1, res


async def case_rearm_sends_finish_days_and_refreshes_expires_at():
    aid = "pr_finish"
    cid = await _seed_campaign(aid, of_id=1701, finish_days=7,
                               expires_at=datetime.utcnow() - timedelta(days=1))
    f = _use_fake(); f.seed(1701, finished=True)
    t0 = datetime.utcnow()
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["reactivated"] == 1, res
    assert f.created[0]["finish_days"] == 7, f.created
    row = await _campaign(cid)
    assert _near(row.expires_at, t0 + timedelta(days=7)), row.expires_at
    # OF's own future finishedAt wins over the guess
    aid = "pr_finish_of"
    cid = await _seed_campaign(aid, of_id=1702, finish_days=7)
    f = _use_fake(); f.seed(1702, finished=True)
    of_end = (datetime.utcnow() + timedelta(days=6, hours=23)).replace(microsecond=0)
    f.finished_at = of_end.isoformat() + "+00:00"
    await run_once(aid, "promo_reactivate", payload=GO)
    assert (await _campaign(cid)).expires_at == of_end
    # never sent → not sent back, and no expiry known
    aid = "pr_finish_none"
    cid = await _seed_campaign(aid, of_id=1703)
    f = _use_fake(); f.seed(1703, finished=True)
    await run_once(aid, "promo_reactivate", payload=GO)
    assert "finish_days" not in f.created[0] and (await _campaign(cid)).expires_at is None, f.created


async def case_dry_run_and_rule_off_queue_no_recheck():
    aid = "pr_nore_dry"
    await _seed_campaign(aid, of_id=1801, subscribe_counts=10)
    f = _use_fake(); f.seed(1801, finished=False, counts=10, claims=9)
    res = await run_once(aid, "promo_reactivate", payload={})
    assert "recheck" not in res and await _rechecks(aid) == [], res
    aid = "pr_nore_off"
    await _seed_campaign(aid, of_id=1802, subscribe_counts=10)
    f = _use_fake(); f.seed(1802, finished=False, counts=10, claims=9)
    rid = await _rule(aid)
    orig = pr.of_pacing.walk

    async def walk_then_switch_off(*a, **kw):   # the operator unticks mid-run
        async with get_session() as s:
            (await s.get(AutomationRule, rid)).is_enabled = False
        return await orig(*a, **kw)
    pr.of_pacing.walk = walk_then_switch_off
    try:
        res = await _run_rule_job(aid, rid)
    finally:
        pr.of_pacing.walk = orig
    assert res["skipped"] == "promo_already_live", res
    assert "recheck" not in res and await _rechecks(aid) == [], res


async def case_deleted_campaign_stops_rearming():
    aid = "pr_deleted"
    cid = await _seed_campaign(aid, of_id=1901)
    f = _use_fake(); f.seed(1901, finished=True)
    async with get_session() as s:
        await s.delete(await s.get(PromoCampaign, cid))
    res = await run_once(aid, "promo_reactivate", payload=GO)
    assert res["managed"] == 0 and f.created == [], res


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
    case_cap_reached_is_rearmed,
    case_near_cap_queues_one_recheck,
    case_expiring_soon_queues_an_expiry_recheck,
    case_expiry_past_but_of_live_retries_bounded,
    case_cooldown_queues_a_recheck_and_never_mints,
    case_rearm_sends_finish_days_and_refreshes_expires_at,
    case_dry_run_and_rule_off_queue_no_recheck,
    case_deleted_campaign_stops_rearming,
)
