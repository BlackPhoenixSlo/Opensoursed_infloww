#!/usr/bin/env python3
from __future__ import annotations

import _harness
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers plugins
import dispatch_plan  # noqa: E402
import event_transcoder  # noqa: E402
import promo_create_guard  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AgencyNotification, AutomationRule, PromoCampaign,  # noqa: E402
                       PromoCreateReservation, PromoKeepState, ScheduledJob, User, UserAccount)
from of_client import OFAPIError  # noqa: E402

BOX = "test-box"
os.environ[promo_create_guard.HOST_ENV] = BOX
KIND = "promo_reactivate"
GO = {"dry_run": False}
SWITCH = "PROMO_PREEMPT_ENABLED"


def _iso(dt: datetime) -> str:
    return dt.isoformat() + "+00:00"


class FakeOF:
    ends_old_on_create = True
    ends_old_on_failed_create = False
    claims_lag = False
    new_starts_at = 0
    finished_at: float | None = None
    created_at_skew = 0.0
    fail_with: Exception | None = None

    def __init__(self):
        self._id = 90_000_000
        self.store: dict[int, dict] = {}
        self.created: list[dict] = []
        self.reads = 0
        self._lag: dict[int, int] = {}

    def seed(self, pid, *, counts=10, claims=0, finished=False, finished_at=None):
        self.store[pid] = {"id": pid, "message": "Promo", "price": 3, "type": "all",
                           "subscribeCounts": counts, "subscribeDays": 30, "createdAt": None,
                           "claimsCount": claims, "isFinished": finished, "finishedAt": finished_at}

    def claims(self, pid, n):
        self.store[pid]["claimsCount"] = n

    def promotions(self, *, offset=0, limit=100):
        items = [dict(p) for p in self.store.values()]
        if offset == 0:
            self.reads += 1
            for p in items:
                if p["id"] in self._lag:
                    p["claimsCount"] = self._lag.pop(p["id"])
        items.sort(key=lambda p: -p["id"])
        return {"hasMore": True, "items": items[offset:offset + limit]}

    def _end_live(self):
        for p in self.store.values():
            p["isFinished"] = True

    def create_promo(self, *, discount, subscribe_counts, subscribe_days=30, message="", type="all",
                     **kw):
        if self.fail_with is not None:
            self.created.append({"failed": True})
            if self.ends_old_on_failed_create:
                self._end_live()
            raise self.fail_with
        old = [p for p in self.store.values() if not p["isFinished"]]
        if self.ends_old_on_create:
            self._end_live()
        self._id += 1
        now = datetime.utcnow()
        fin = None if self.finished_at is None else _iso(now + timedelta(seconds=self.finished_at))
        item = {"id": self._id, "message": message, "price": 3, "type": type,
                "subscribeCounts": subscribe_counts, "subscribeDays": subscribe_days,
                "createdAt": _iso(now + timedelta(seconds=self.created_at_skew)),
                "claimsCount": self.new_starts_at, "isFinished": False, "finishedAt": fin}
        self.store[self._id] = item
        if self.claims_lag and old:
            self._lag[self._id] = int(old[0]["claimsCount"] or 0)
        self.created.append({"discount": discount, "counts": subscribe_counts})
        return [dict(item)]


def _use_fake() -> FakeOF:
    f = FakeOF()
    ax._make_client = lambda account_id: f  # type: ignore[attr-defined]
    return f


async def _seed(aid, *, of_id, counts=10, preempt=True, expires_at=None, finish_days=None) -> int:
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(User(id=f"u_{aid}", username=f"owner_{aid}", password="pw"))
        s.add(UserAccount(user_id=f"u_{aid}", account_id=aid))
        s.add(AutomationRule(account_id=aid, name="keep-seed", kind=KIND, is_enabled=True,
                             trigger_json=json.dumps({"every_seconds": 3600}),
                             steps_json=json.dumps(GO)))
        row = PromoCampaign(
            account_id=aid, of_promo_id=of_id, name="Summer", discount_percent=50, price_cents=0,
            subscribe_counts=counts, subscribe_days=30, message="Promo", promo_type="all",
            status="active", subscriber_count=0, auto_reactivate=True, reactivate_count=0,
            created_at=datetime.utcnow(), keep_host_id=BOX, preempt=preempt,
            expires_at=expires_at, finish_days=finish_days)
        s.add(row)
        await s.flush()
        return row.id


async def _campaign(cid) -> PromoCampaign:
    async with get_session() as s:
        return await s.get(PromoCampaign, cid)


async def _reservations(aid) -> list[PromoCreateReservation]:
    async with get_session() as s:
        return list((await s.execute(select(PromoCreateReservation).where(
            PromoCreateReservation.account_id == aid).order_by(PromoCreateReservation.id))).scalars())


async def _state(aid) -> PromoKeepState | None:
    async with get_session() as s:
        return await s.get(PromoKeepState, aid)


async def _notices(aid) -> list[str]:
    async with get_session() as s:
        return [n.text for n in (await s.execute(select(AgencyNotification).where(
            AgencyNotification.account_id == aid,
            AgencyNotification.kind == "promo_keep_running"))).scalars()]


async def _age_all(aid, seconds) -> None:
    back = timedelta(seconds=seconds)
    async with get_session() as s:
        for (r,) in await s.execute(select(PromoCreateReservation).where(
                PromoCreateReservation.account_id == aid)):
            for col in ("created_at", "sent_at", "settled_at", "listed_at", "not_before"):
                if getattr(r, col) is not None:
                    setattr(r, col, getattr(r, col) - back)
        for (c,) in await s.execute(select(PromoCampaign).where(PromoCampaign.account_id == aid)):
            if c.last_reactivated_at is not None:
                c.last_reactivated_at -= back


class _Switch:
    def __init__(self, value: str):
        self.value = value

    def __enter__(self):
        self._old = os.environ.get(SWITCH)
        os.environ[SWITCH] = self.value

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop(SWITCH, None)
        else:
            os.environ[SWITCH] = self._old


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.headers = status, text, {}



async def case_fill_preempts_at_trusted_count():
    aid = "pp_fill"
    cid = await _seed(aid, of_id=501)
    f = _use_fake(); f.seed(501, claims=0)
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "promo_already_live" and "wait_reason" not in res, res
    f.claims(501, 8)
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "promo_already_live" and f.created == [], res
    f.claims(501, 9)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and res["source"] == "auto_fill", res
    assert f.store[501]["isFinished"], "OF ends the old promo at the POST"
    row = await _campaign(cid)
    new_id = row.of_promo_id
    assert new_id not in (None, 501) and row.auto_reactivate, row.of_promo_id
    (r,) = await _reservations(aid)
    assert (r.source, r.state, r.claims_seen, r.first_claims) == ("auto_fill", "created", 9, 0), r
    assert any("after the last promo filled" in t for t in await _notices(aid)), await _notices(aid)
    res = await run_once(aid, KIND, payload=GO)
    st = await _state(aid)
    assert (st.kept_of_promo_id, st.first_claims) == (new_id, 0), (st.kept_of_promo_id, st.first_claims)
    assert st.skew_s is not None and abs(st.skew_s) <= 1, st.skew_s
    f.claims(new_id, 9)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "cooldown" and len(f.created) == 1, res
    await _age_all(aid, 121)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and res["source"] == "auto_fill", res


async def case_switch_off_or_preempt_off_after_end():
    for aid, preempt, switch in (("pp_switch_off", True, "0"), ("pp_tick_off", False, "1")):
        await _seed(aid, of_id=601 if preempt else 602, preempt=preempt)
        pid = 601 if preempt else 602
        f = _use_fake(); f.seed(pid, claims=0)
        with _Switch(switch):
            await run_once(aid, KIND, payload=GO)
            f.claims(pid, 9)
            res = await run_once(aid, KIND, payload=GO)
            assert res["skipped"] == "promo_already_live" and f.created == [], (aid, res)
            assert "wait_reason" not in res, res
            f.claims(pid, 10)
            res = await run_once(aid, KIND, payload=GO)
            assert res["reactivated"] == 1 and "source" not in res, (aid, res)
        (r,) = await _reservations(aid)
        assert r.source == "auto_ended", (aid, r.source)


async def case_mn01_lagging_or_nonzero_new_count_waits():
    aid = "pp_mn01_first"
    await _seed(aid, of_id=701)
    f = _use_fake(); f.seed(701, claims=3)
    await run_once(aid, KIND, payload=GO)
    f.claims(701, 9)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "count_untrusted" and f.created == [], res
    assert (await _state(aid)).wait_reason == "count_untrusted"
    for aid, mode in (("pp_mn01_lag", {"claims_lag": True}), ("pp_mn01_start", {"new_starts_at": 2})):
        cid = await _seed(aid, of_id=702 if mode.get("claims_lag") else 703)
        f = _use_fake()
        pid = 702 if mode.get("claims_lag") else 703
        for k, v in mode.items():
            setattr(f, k, v)
        f.seed(pid, claims=0)
        await run_once(aid, KIND, payload=GO)
        f.claims(pid, 9)
        res = await run_once(aid, KIND, payload=GO)
        assert res["source"] == "auto_fill", (aid, res)
        new_id = (await _campaign(cid)).of_promo_id
        res = await run_once(aid, KIND, payload=GO)
        assert res["wait_reason"] == "count_untrusted", (aid, res)
        f.claims(new_id, 9)
        res = await run_once(aid, KIND, payload=GO)
        assert res["wait_reason"] == "count_untrusted" and len(f.created) == 1, (aid, res)


async def case_mn04_failed_preempt_falls_back_after_backoff():
    aid = "pp_mn04_fail"
    cid = await _seed(aid, of_id=801)
    f = _use_fake(); f.seed(801, claims=0)
    f.ends_old_on_failed_create = True
    await run_once(aid, KIND, payload=GO)
    f.claims(801, 9)
    f.fail_with = OFAPIError("429 for /promotions\n", response=_Resp(429))
    res = await run_once(aid, KIND, payload=GO)
    assert (res["create"], res["warning"], res["source"]) == ("failed", "no_promo_may_be_live", "auto_fill"), res
    assert any("no promo may be live" in t for t in await _notices(aid)), await _notices(aid)
    assert f.store[801]["isFinished"], "OF ended the old promo though the create failed"
    f.fail_with = None
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "backoff" and len(f.created) == 1, res
    await _age_all(aid, 121)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and "source" not in res, res
    assert [r.source for r in await _reservations(aid)] == ["auto_fill", "auto_ended"]
    assert (await _campaign(cid)).auto_reactivate


async def case_mn04_no_recovery_slot_no_preempt():
    aid = "pp_mn04_slot"
    await _seed(aid, of_id=901)
    f = _use_fake(); f.seed(901, claims=0)
    now = datetime.utcnow()
    async with get_session() as s:
        for m in (10, 20):
            s.add(PromoCreateReservation(
                account_id=aid, source="auto_ended", state="cleared", terms_json="{}",
                created_at=now - timedelta(minutes=m)))
    await run_once(aid, KIND, payload=GO)
    f.claims(901, 9)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "no_recovery_slot" and f.created == [], res
    assert (await _state(aid)).wait_reason == "no_recovery_slot"
    f.claims(901, 10)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and "source" not in res, res
    assert (await _state(aid)).wait_reason is None


async def case_switch_off_at_the_sending_cas():
    aid = "pp_cas_switch"
    await _seed(aid, of_id=1001)
    f = _use_fake(); f.seed(1001, claims=0)
    await run_once(aid, KIND, payload=GO)
    f.claims(1001, 9)
    real_mark = promo_create_guard.mark_sending

    async def flip_then_mark(res, recheck):
        os.environ[SWITCH] = "0"
        return await real_mark(res, recheck)
    promo_create_guard.mark_sending = flip_then_mark
    try:
        res = await run_once(aid, KIND, payload=GO)
    finally:
        promo_create_guard.mark_sending = real_mark
        os.environ.pop(SWITCH, None)
    assert res["skipped"] == "not_sent" and f.created == [], res
    (r,) = await _reservations(aid)
    assert (r.state, r.error_class) == ("failed", "not_sent"), (r.state, r.error_class)



async def _timed_setup(aid, *, counts=10, finished_at=100.0, skew=0.0):
    cid = await _seed(aid, of_id=1100, counts=counts)
    f = _use_fake(); f.seed(1100, counts=counts, finished=True)
    f.finished_at, f.created_at_skew = finished_at, skew
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1, res
    return f, cid, (await _campaign(cid)).of_promo_id


async def case_timed_preempts_before_of_end():
    aid = "pp_timed"
    f, cid, pid = await _timed_setup(aid)
    await _age_all(aid, 700)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "end_unconfirmed" and len(f.created) == 1, res
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and res["source"] == "auto_timed", res
    assert f.store[pid]["isFinished"]
    assert [r.source for r in await _reservations(aid)] == ["auto_ended", "auto_timed"]
    assert any("after the last promo was ending" in t for t in await _notices(aid))


async def case_rvb_c7_guessed_end_only_its_expiry_check():
    aid = "pp_mn08_guess"
    exp = datetime.utcnow() + timedelta(seconds=200)
    await _seed(aid, of_id=1200, expires_at=exp, finish_days=1)
    f = _use_fake(); f.seed(1200, claims=0, finished_at=None)
    async with get_session() as s:
        s.add(PromoKeepState(account_id=aid, skew_s=0))
    res = await run_once(aid, KIND, payload=GO)
    assert res["recheck"]["reason"] == "expiry" and f.created == [], res
    at = datetime.fromisoformat(res["recheck"]["at"])
    assert abs((at - (exp + timedelta(seconds=30))).total_seconds()) < 2, at
    aid = "pp_c7_noclock"
    await _seed(aid, of_id=1210)
    f = _use_fake(); f.seed(1210, claims=0, finished_at=_iso(datetime.utcnow() + timedelta(seconds=600)))
    res = await run_once(aid, KIND, payload=GO)
    assert "recheck" not in res and f.created == [], res
    aid = "pp_c7_clock"
    end = datetime.utcnow() + timedelta(seconds=600)
    await _seed(aid, of_id=1220)
    f = _use_fake(); f.seed(1220, claims=0, finished_at=_iso(end))
    async with get_session() as s:
        s.add(PromoKeepState(account_id=aid, skew_s=20))
    res = await run_once(aid, KIND, payload=GO)
    assert res["recheck"]["reason"] == "timed", res
    at = datetime.fromisoformat(res["recheck"]["at"])
    assert abs((at - (end + timedelta(seconds=20 - 115))).total_seconds()) < 2, at


async def case_mn08_finished_at_changed_waits():
    aid = "pp_mn08_moved"
    f, cid, pid = await _timed_setup(aid)
    await _age_all(aid, 700)
    await run_once(aid, KIND, payload=GO)
    f.store[pid]["finishedAt"] = _iso(datetime.utcnow() + timedelta(seconds=90))
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "end_unconfirmed" and len(f.created) == 1, res


async def case_mn08_skew_waits():
    aid = "pp_mn08_skew"
    f, cid, pid = await _timed_setup(aid, skew=45)
    assert (await _state(aid)).skew_s == -45, (await _state(aid)).skew_s
    await _age_all(aid, 700)
    await run_once(aid, KIND, payload=GO)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "clock" and len(f.created) == 1, res
    assert (await _state(aid)).wait_reason == "clock"


async def case_mn08_cap9_never_timed():
    aid = "pp_mn08_cap9"
    f, cid, pid = await _timed_setup(aid, counts=9)
    await _age_all(aid, 700)
    for _ in range(3):
        res = await run_once(aid, KIND, payload=GO)
        assert res["skipped"] == "promo_already_live" and "wait_reason" not in res, res
    assert len(f.created) == 1



async def _burst_reads(aid, f: FakeOF, frames: list[int]) -> int:
    async with get_session() as s:
        rid = (await s.execute(select(AutomationRule.id).where(
            AutomationRule.account_id == aid, AutomationRule.kind == KIND))).scalar_one()
        s.add(ScheduledJob(account_id=aid, kind=KIND, payload_json=json.dumps(GO), status="done",
                           run_at=datetime.utcnow(), rule_id=rid,
                           created_at=datetime.utcnow() - timedelta(seconds=dispatch_plan.POKE_FLOOR_S + 1)))
    before = f.reads
    for n in frames:
        await event_transcoder.transcode({"toasts": [{"type": "subscribed"}] * n, "__account_id": aid})
    await ax._materialize_due_rules()
    for _ in range(5):
        if (await run_once(aid, KIND)).get("reason") == "no_job":
            break
    return f.reads - before


async def case_toast_burst_reads():
    aid = "pp_toast_far"
    await _seed(aid, of_id=1301, counts=50)
    f = _use_fake(); f.seed(1301, counts=50, claims=2)
    await run_once(aid, KIND, payload=GO)
    assert await _burst_reads(aid, f, [1, 1, 3, 1]) == 0
    aid = "pp_toast_near"
    await _seed(aid, of_id=1302, counts=50)
    f = _use_fake(); f.seed(1302, counts=50, claims=40)
    await run_once(aid, KIND, payload=GO)
    assert await _burst_reads(aid, f, [1, 1, 1, 1]) == 1



class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    def __enter__(self):
        logging.getLogger("of-relay.automation.promo_reactivate").addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger("of-relay.automation.promo_reactivate").removeHandler(self)


async def case_rvb_r1_replaced_still_live_stands_down():
    aid = "pp_r1"
    cid = await _seed(aid, of_id=1401)
    f = _use_fake(); f.seed(1401, claims=0)
    f.ends_old_on_create = False
    await run_once(aid, KIND, payload=GO)
    f.claims(1401, 9)
    res = await run_once(aid, KIND, payload=GO)
    assert res["source"] == "auto_fill", res
    new_id = (await _campaign(cid)).of_promo_id
    second = lambda logs: [x for x in logs.lines if x.startswith("promo_keep_second_live")]  # noqa: E731
    with _Logs() as logs:
        res = await run_once(aid, KIND, payload=GO)
        assert res["skipped"] == "promo_already_live" and res["wait_reason"] == "second_live", res
        assert len(f.created) == 1 and second(logs) == [], (f.created, logs.lines)
    await _age_all(aid, 601)
    f.claims(new_id, 9)
    for switch in ("1", "0"):
        with _Switch(switch), _Logs() as logs:
            res = await run_once(aid, KIND, payload=GO)
            assert res["skipped"] == "promo_already_live" and len(f.created) == 1, (switch, res)
            assert len(second(logs)) == 1 and str(new_id) in second(logs)[0], (switch, logs.lines)
    f.store[new_id]["isFinished"] = True
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "promo_already_live" and res["live_of_promo_id"] == 1401, res
    assert len(f.created) == 1


async def case_rvb_r2_refused_fill_keeps_running():
    aid = "pp_r2_400"
    cid = await _seed(aid, of_id=1501)
    f = _use_fake(); f.seed(1501, claims=0)
    f.ends_old_on_failed_create = True
    await run_once(aid, KIND, payload=GO)
    f.claims(1501, 9)
    f.fail_with = OFAPIError("400 for /promotions\n", response=_Resp(400, "bad request"))
    res = await run_once(aid, KIND, payload=GO)
    assert (res["create"], res["error_class"]) == ("failed", "http_400"), res
    c = await _campaign(cid)
    assert (c.auto_reactivate, c.preempt, c.keep_warning) == (True, False, None), \
        (c.auto_reactivate, c.preempt, c.keep_warning)
    assert any("Re-create at 90% filled is off" in t for t in await _notices(aid)), await _notices(aid)
    f.fail_with = None
    await _age_all(aid, 121)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and "source" not in res, res
    assert [r.source for r in await _reservations(aid)] == ["auto_fill", "auto_ended"]


async def _pending_rechecks(aid) -> list[dict]:
    async with get_session() as s:
        return [json.loads(j.payload_json) for j in (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND,
            ScheduledJob.status == "pending"))).scalars()]


async def case_rvb_c5_failed_fill_queues_one_recovery():
    from automations import promo_reactivate as pr
    aid = "pp_c5"
    await _seed(aid, of_id=1601)
    f = _use_fake(); f.seed(1601, claims=0)
    f.ends_old_on_failed_create = True
    await run_once(aid, KIND, payload=GO)
    f.claims(1601, 9)
    f.fail_with = OFAPIError("429 for /promotions\n", response=_Resp(429))
    res = await run_once(aid, KIND, payload=GO)
    assert res["create"] == "failed" and res["recheck"]["reason"] == "recovery", res
    (r,) = await _reservations(aid)
    at = datetime.fromisoformat(res["recheck"]["at"])
    assert abs((at - (r.not_before + timedelta(seconds=5))).total_seconds()) < 1, (at, r.not_before)
    assert pr._gate.get(aid) is None, "the toast gate forgets the promo OF may have ended"
    f.fail_with = None
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "backoff" and "recheck" not in res, res
    jobs = await _pending_rechecks(aid)
    assert [j.get("_recheck") for j in jobs] == ["recovery"], jobs


async def case_f4_recovery_moves_a_distant_recheck_earlier():
    from automations import promo_reactivate as pr
    aid = "pp_f4"
    await _seed(aid, of_id=1611)
    f = _use_fake(); f.seed(1611, claims=0)
    f.ends_old_on_failed_create = True
    await run_once(aid, KIND, payload=GO)
    far = datetime.utcnow() + timedelta(seconds=2400)
    held = await pr._queue_recheck(aid, GO, "timed", far)
    assert held is not None and held["reason"] == "timed", held
    jid = (await _state(aid)).recheck_job_id
    f.claims(1611, 9)
    f.fail_with = OFAPIError("429 for /promotions\n", response=_Resp(429))
    res = await run_once(aid, KIND, payload=GO)
    assert res["create"] == "failed" and (res.get("recheck") or {}).get("reason") == "recovery", res
    (r,) = await _reservations(aid)
    want = r.not_before + timedelta(seconds=5)
    async with get_session() as s:
        jobs = list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND,
            ScheduledJob.status == "pending"))).scalars())
    assert [j.id for j in jobs] == [jid], jobs
    assert abs((jobs[0].run_at - want).total_seconds()) < 1, (jobs[0].run_at, want)
    body = json.loads(jobs[0].payload_json)
    assert (body.get("_recheck"), body.get("dry_run")) == ("recovery", False), body
    st = await _state(aid)
    assert (st.recheck_job_id, st.recheck_at) == (jid, jobs[0].run_at), (st.recheck_job_id, st.recheck_at)
    assert await pr._queue_recheck(aid, GO, "expiry", far) is None
    assert (await _state(aid)).recheck_at == jobs[0].run_at


async def case_f5_dead_session_fill_promises_no_wait():
    aid = "pp_f5"
    await _seed(aid, of_id=1621)
    f = _use_fake(); f.seed(1621, claims=0)
    f.ends_old_on_failed_create = True
    await run_once(aid, KIND, payload=GO)
    f.claims(1621, 9)
    f.fail_with = OFAPIError('400 for /promotions\n{"error":{"code":301,"message":"Wrong user."}}',
                             response=_Resp(400, '{"error":{"code":301,"message":"Wrong user."}}'))
    res = await run_once(aid, KIND, payload=GO)
    assert (res["create"], res["error_class"]) == ("failed", "session_dead") and "recheck" not in res, res
    assert await _pending_rechecks(aid) == []
    (text,) = [t for t in await _notices(aid) if "early re-create" in t]
    assert "short wait" not in text and "logged in again" in text, text


async def case_f7_early_returns_clear_wait_reason():
    aid = "pp_f7_clear"
    cid = await _seed(aid, of_id=1631)
    f = _use_fake(); f.seed(1631, claims=0)

    async def stale():
        async with get_session() as s:
            await s.merge(PromoKeepState(account_id=aid, wait_reason="count_untrusted"))

    async def fence(host):
        async with get_session() as s:
            (await s.get(PromoCampaign, cid)).keep_host_id = host
    await stale(); await fence("box-elsewhere")
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "fence" and (await _state(aid)).wait_reason is None, res
    await stale(); await fence(BOX)

    def down(**kw):
        raise OFAPIError("500 for /promotions\n", response=_Resp(500))
    f.promotions = down
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "of_unreachable" and (await _state(aid)).wait_reason is None, res
    await stale()
    async with get_session() as s:
        (await s.get(PromoCampaign, cid)).auto_reactivate = False
    res = await run_once(aid, KIND, payload=GO)
    assert res["managed"] == 0 and (await _state(aid)).wait_reason is None, res
    await stale()
    res = await run_once(aid, KIND, payload={})
    assert (await _state(aid)).wait_reason == "count_untrusted", res


async def case_rvb_c6_racing_observe_keeps_drop():
    from automations import promo_reactivate as pr
    aid = "pp_c6"
    async with get_session() as s:
        s.add(Account(id=aid))
        await s.flush()
        s.add(PromoKeepState(account_id=aid, kept_of_promo_id=1701, first_claims=0, last_claims=8,
                             read_at=datetime.utcnow()))

    def read(n):
        return [{"of_promo_id": 1701, "is_finished": False, "cap_inferred": False,
                 "claims_present": True, "subscriber_count": n, "subscribe_counts": 50,
                 "finished_at": None}]
    now = datetime.utcnow()
    (_, a, _), (_, b, _) = await asyncio.gather(pr._observe(aid, read(7), {1701}, now),
                                                pr._observe(aid, read(9), {1701}, now))
    st = await _state(aid)
    assert st.first_claims is None, (st.first_claims, st.last_claims)
    assert a.first_claims is None, (a, b)


async def case_rvb_r3_timed_in_of_time():
    aid = "pp_r3"
    f, cid, pid = await _timed_setup(aid, finished_at=130.0, skew=25.0)
    assert (await _state(aid)).skew_s == -25, (await _state(aid)).skew_s
    await _age_all(aid, 700)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "end_unconfirmed", res
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and res["source"] == "auto_timed", res



async def _run_due(aid, within_s=30) -> list[dict]:
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND, ScheduledJob.status == "pending",
            ScheduledJob.run_at <= datetime.utcnow() + timedelta(seconds=within_s))
            .values(run_at=datetime.utcnow()))
    out = []
    for _ in range(5):
        res = await run_once(aid, KIND)
        if res.get("reason") == "no_job":
            break
        out.append(res)
    return out


async def case_f1_fill_fires_on_own_create():
    aid = "pp_f1_own"
    cid = await _seed(aid, of_id=1801)
    f = _use_fake(); f.seed(1801, finished=True)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1, res
    new_id = (await _campaign(cid)).of_promo_id
    ran = await _run_due(aid)
    assert [r.get("skipped") for r in ran] == ["promo_already_live"], ran
    f.claims(new_id, 5)
    res = await run_once(aid, KIND, payload=GO)
    assert res["skipped"] == "promo_already_live" and "wait_reason" not in res, res
    f.claims(new_id, 9)
    await _age_all(aid, 121)
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1 and res["source"] == "auto_fill", res
    aid = "pp_f1_answer"
    cid = await _seed(aid, of_id=1802)
    f = _use_fake(); f.seed(1802, finished=True)
    f.new_starts_at = 3
    res = await run_once(aid, KIND, payload=GO)
    assert res["reactivated"] == 1, res
    new_id = (await _campaign(cid)).of_promo_id
    f.claims(new_id, 0)
    await _run_due(aid)
    f.claims(new_id, 9)
    await _age_all(aid, 121)
    res = await run_once(aid, KIND, payload=GO)
    assert res["wait_reason"] == "count_untrusted" and len(f.created) == 1, res


_harness.run()
