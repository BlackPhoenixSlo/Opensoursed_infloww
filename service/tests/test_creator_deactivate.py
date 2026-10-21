#!/usr/bin/env python3
"""
Creator deactivate — `POST /admin/accounts/{id}/active` and every loop that
must stop for a deactivated Creator (service/account_health.py "Deactivation").

  case_chatter_cannot_toggle:
      a chatter session is refused (403): the switch is owner-only.
  case_foreign_owner_cannot_toggle:
      an owner toggling another owner's Creator is refused (403).
  case_owner_deactivates:
      200; the Creator's pump is stopped and its OF client dropped; the default
      account is left alone (its file is shared); GET /admin/accounts and
      /chatter/me/accounts still list it, stamped is_active=false, beside an
      active Creator.
  case_of_write_to_deactivated_creator_is_409:
      a POST under /api/of/ for the deactivated Creator answers 409 before any
      handler runs, named explicitly or reached through the default-account
      fallback; a read for it, and a write for an active Creator, pass.
  case_of_client_refuses_every_write_for_a_deactivated_creator:
      OFClient._http_call refuses every write for the deactivated Creator
      before anything is sent (so /admin/* routes and jobs are covered too);
      its GET and an active Creator's writes reach the wire; the refusal is
      transient to the automations' fan classifiers.
  case_carrier_removal_is_the_one_write_let_through:
      remove_carrier deletes a carrier for the deactivated Creator (that call
      only), and the vault sweep deletes a dead import's carrier for it.
  case_a_refused_write_through_proxy_is_the_guards_409:
      `_proxy` answers the refusal with the hook's 409 account_deactivated.
  case_write_gate_loads_once_and_follows_the_switch:
      deactivated_ids() only reads; load_write_gate() fills the gate, and
      activate/deactivate open and shut it.
  case_link_prewarm_skips:
      the hourly tracking-link prewarm (reads plus add-to-list writes) skips it.
  case_of_stats_daily_skips:
      the daily OF statistics fetch skips it.
  case_pump_never_starts_for_a_deactivated_creator:
      the pump coroutine itself (what _restart_account_pump spawns) returns
      before loading a client for a deactivated Creator.
  case_health_all_accounts_skips:
      the Creators page's all-accounts probe answers a deactivated Creator off
      the flag, without an OF call.
  case_pump_supervisor_skips_and_reaps:
      one supervisor pass starts no pump for the deactivated Creator and stops
      the one it had.
  case_chat_link_seed_skips:
      the startup scrape_chats seed enqueues for the active Creator only.
  case_ledger_polls_skip:
      the 5-min ledger supervisor and the 30s fast poll tick the active
      Creator only.
  case_executor_skips:
      _due_job_pairs leaves the deactivated Creator's due job unspawned (still
      pending), and a direct run_once returns skipped/account_deactivated
      without running the automation.
  case_dead_session_probe_skips:
      a deactivated Creator whose session is flagged dead gets no recovery
      probe (an OF call).
  case_reactivate_after_long_gap_backfills:
      activating a Creator off for longer than the 7-day refresh window asks
      for a backfill from the deactivation on; a short gap asks for none.
  case_reactivate_cancels_jobs_missed_while_off:
      activating cancels the pending jobs that fell due while the Creator was
      off; one due before the deactivation, one due later, and a cleanup
      (unsend_messages) job that fell due while off stay pending.
  case_trigger_backfill_reopens_the_window:
      on an account already fully backfilled, trigger_backfill's next backfill
      window runs from now down to `since` (it used to sit wholly below it).

No network: the registry, pumps and OF calls are all stubbed.

Run: ./venv/bin/python service/tests/test_creator_deactivate.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import link_metrics  # noqa: E402
import of_client  # noqa: E402
import of_stats_daily  # noqa: E402
import transaction_ingest as ti  # noqa: E402
import vault_upload  # noqa: E402
from of_client import OFClient, OFDeactivatedError  # noqa: E402
from automation_registry import register  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountHealth, Chatter, ChatterUser, ScheduledJob,
    TransactionScanHistory, User, UserAccount,
)

_harness.make_client()  # neutralises the startup spawns before `server` serves
import server  # noqa: E402

OFF, ON, FOREIGN = "acc_off", "acc_on", "acc_foreign"
_ACCOUNTS = (OFF, ON, FOREIGN)

# ── Registry + side effects, in memory ───────────────────────────────
account_registry.get_account = lambda aid: {"id": aid} if aid in _ACCOUNTS else None
account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in _ACCOUNTS]
account_registry.is_account = lambda aid: aid in _ACCOUNTS
_ACTIVE: dict[str, str | None] = {"id": OFF}
account_registry.get_active_account_id = lambda: _ACTIVE["id"]
account_registry.set_active_account_id = lambda aid: _ACTIVE.__setitem__("id", aid)

STOPPED: list[str] = []
STARTED: list[str] = []
DROPPED: list[str] = []
server._stop_account_pump = STOPPED.append
server._start_account_pump = STARTED.append
server._invalidate_client = DROPPED.append

CALLS = {"noop": 0}


@register("t_deact_noop")
async def _t_noop(account_id: str, payload: dict, *, run_id: int) -> dict:
    CALLS["noop"] += 1
    return {}


async def _setup() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        other = User(id=uuid.uuid4().hex, username="other", password="pw")
        s.add_all([boss, other])
        s.add_all([Account(id=a, nickname=a) for a in _ACCOUNTS])
        cid = uuid.uuid4().hex
        s.add(Chatter(id=cid, username="chat", password="pw", display_name="Chat",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
        await s.flush()
        s.add_all([
            UserAccount(user_id=boss.id, account_id=OFF),
            UserAccount(user_id=boss.id, account_id=ON),
            UserAccount(user_id=other.id, account_id=FOREIGN),
        ])
        s.add(ChatterUser(chatter_id=cid, user_id=boss.id, created_at=datetime.utcnow()))


asyncio.run(_setup())


def _login(path: str, username: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post(path, json={"username": username, "password": "pw"})
    assert r.status_code == 200, f"{username} login failed: {r.status_code} {r.text}"
    return c


async def _backdate_deactivation(aid: str, ago: timedelta) -> None:
    async with get_session() as s:
        await s.execute(update(AccountHealth).where(AccountHealth.account_id == aid)
                        .values(deactivated_at=datetime.utcnow() - ago))


async def _run_briefly(coro) -> None:
    """One pass of a `while True` supervisor: let it reach its first sleep."""
    task = asyncio.create_task(coro)
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── Cases ────────────────────────────────────────────────────────────

def case_chatter_cannot_toggle() -> None:
    r = _login("/chatter/login", "chat").post(f"/admin/accounts/{OFF}/active", json={"active": False})
    assert r.status_code == 403, f"chatter toggled a Creator: {r.status_code} {r.text}"


def case_foreign_owner_cannot_toggle() -> None:
    r = _login("/auth/login", "other").post(f"/admin/accounts/{OFF}/active", json={"active": False})
    assert r.status_code == 403, f"another owner toggled the Creator: {r.status_code} {r.text}"


async def case_owner_deactivates() -> None:
    owner = _login("/auth/login", "boss")
    r = owner.post(f"/admin/accounts/{OFF}/active", json={"active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False, r.text
    assert await account_health.is_deactivated(OFF)
    assert OFF in STOPPED and OFF in DROPPED, "pump/client not stopped on deactivate"
    assert _ACTIVE["id"] == OFF, f"the shared default account was moved: {_ACTIVE}"

    rows = {a["id"]: a for a in owner.get("/admin/accounts").json()["accounts"]}
    assert set(rows) == {OFF, ON}, f"a deactivated Creator must stay listed: {sorted(rows)}"
    assert rows[OFF]["is_active"] is False and rows[ON]["is_active"] is True, rows

    flat = {a["account_id"]: a for a in _login("/chatter/login", "chat").get("/chatter/me/accounts").json()}
    assert set(flat) == {OFF, ON}, f"chatter list dropped a row: {sorted(flat)}"
    assert flat[OFF]["is_active"] is False and flat[ON]["is_active"] is True, flat


async def case_of_write_to_deactivated_creator_is_409() -> None:
    owner = _login("/auth/login", "boss")
    r = owner.post("/api/of/v2/chats/123/mark-as-read", headers={"X-Account-Id": OFF})
    assert r.status_code == 409, f"write to a deactivated Creator: {r.status_code} {r.text}"
    assert r.json()["detail"]["error"] == "account_deactivated"
    # No explicit id: the route would fall back to the default account, which is
    # still the deactivated Creator.
    assert _ACTIVE["id"] == OFF
    r = owner.post("/api/of/v2/chats/123/mark-as-read")
    assert r.status_code == 409, f"fallback write to a deactivated Creator: {r.status_code} {r.text}"

    # The guard passes everything else through to the handler.
    class _Req:
        def __init__(self, method: str, aid: str | None) -> None:
            self.method = method
            self.headers = {"x-account-id": aid} if aid else {}
            self.query_params: dict = {}
            self.url = type("U", (), {"path": "/api/of/v2/chats/123/mark-as-read"})()

    async def _next(_req):
        return "handler"

    assert await server._deactivated_write_guard(_Req("GET", OFF), _next) == "handler", "read refused"
    assert await server._deactivated_write_guard(_Req("POST", ON), _next) == "handler", \
        "write to an active Creator refused"
    _ACTIVE["id"] = ON
    try:
        assert await server._deactivated_write_guard(_Req("POST", None), _next) == "handler", \
            "fallback write to an active default refused"
    finally:
        _ACTIVE["id"] = OFF


class _Wired:
    """An OFClient with no session whose transport records what would have gone
    out (`sent`, "METHOD /path") and answers 204: every gate in _http_call runs."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def client(self, aid: str) -> OFClient:
        c = object.__new__(OFClient)  # no session, no curl handle
        c.account_id, c.proxy_label = aid, None
        c._ensure_x_hash = lambda: "h"
        c._persist_cf_cookies = lambda r: None
        c._note_signed_ok = lambda url, r: None

        def _transport(_fn, *, what="", **_k):
            self.sent.append(what)
            return type("R", (), {"ok": True, "status_code": 204, "text": "", "headers": {}})()
        c._proxy_retry = _transport
        return c


async def case_of_client_refuses_every_write_for_a_deactivated_creator() -> None:
    wire = _Wired()
    off, on = wire.client(OFF), wire.client(ON)
    for call in (lambda: off.create_vault_list("x"), lambda: off.mark_chat_read(1),
                 lambda: off.delete_post(7), lambda: off.request_json("PUT", "/api2/v2/posts/7")):
        try:
            call()
        except OFDeactivatedError as e:
            assert "deactivated" in str(e), e
        else:
            raise AssertionError("a write for a deactivated Creator went out")
    assert wire.sent == [], f"refused writes reached the wire: {wire.sent}"
    off.request_json("GET", "/api2/v2/vault/lists")
    on.create_vault_list("x")
    on.delete_post(7)
    assert wire.sent == ["GET /api2/v2/vault/lists", "POST /api2/v2/vault/lists",
                         "DELETE /api2/v2/posts/7"], wire.sent

    # Transient for the automations: no fan is skip-listed or quarantined over it,
    # and the account is not flagged session-dead.
    from automations._common import is_media_rejected_error, is_unreachable_fan_error
    e = OFDeactivatedError("refused: POST /api2/v2/messages (Creator deactivated)")
    assert not is_unreachable_fan_error(e) and not is_media_rejected_error(e)
    assert account_health.is_session_dead_error(e) is None


async def case_carrier_removal_is_the_one_write_let_through() -> None:
    wire = _Wired()
    off = wire.client(OFF)
    of_client.remove_carrier(off, 9001)
    assert wire.sent == ["DELETE /api2/v2/posts/9001"], wire.sent
    # The flag covers that one call, not what follows it.
    try:
        off.delete_post(9002)
    except OFDeactivatedError:
        pass
    else:
        raise AssertionError("the carrier exemption leaked past remove_carrier")

    # The hourly sweep finds a dead import's carrier on the deactivated
    # Creator and deletes it: left alone it would publish on the feed.
    saved = vault_upload.SPOOL_ROOT, vault_upload.LOCK_DIR, vault_upload.STAGE_ROOT
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        vault_upload.SPOOL_ROOT, vault_upload.LOCK_DIR = root, root / "locks"
        vault_upload.STAGE_ROOT = root / "incoming"
        try:
            run_id = f"{OFF}-20260101T000000-aaaaaa"
            (root / run_id).mkdir()
            item = vault_upload._item("v.mp4", None, "local", 10)
            item.update(carrier_post_id=9003, carrier_deleted=False, status="uploading")
            state = vault_upload._new_state(run_id, OFF, None)
            state.update(status="failed", items=[item], finished_at=vault_upload._now())
            (root / run_id / "run.json").write_text(json.dumps(state))
            res = vault_upload.sweep(lambda aid: off)
            after = json.loads((root / run_id / "run.json").read_text())
        finally:
            vault_upload.SPOOL_ROOT, vault_upload.LOCK_DIR, vault_upload.STAGE_ROOT = saved
    assert "DELETE /api2/v2/posts/9003" in wire.sent, wire.sent
    assert res["carriers_deleted"] == 1 and after["items"][0]["carrier_deleted"] is True, (res, after)


async def case_a_refused_write_through_proxy_is_the_guards_409() -> None:
    off = _Wired().client(OFF)
    try:
        server._proxy(lambda: off.hide_chat(1))
    except HTTPException as e:
        assert e.status_code == 409 and e.detail == server._DEACTIVATED_DETAIL, (e.status_code, e.detail)
    else:
        raise AssertionError("the refusal was not a 409")


async def case_write_gate_loads_once_and_follows_the_switch() -> None:
    account_health._writes_off = frozenset()
    await account_health.deactivated_ids()
    assert not account_health.refuses_writes(OFF), "deactivated_ids() must only read"
    await account_health.load_write_gate()
    assert account_health.refuses_writes(OFF) and not account_health.refuses_writes(ON)
    assert await account_health.activate(OFF) is not None
    assert not account_health.refuses_writes(OFF), "activate left the gate shut"
    assert await account_health.deactivate(OFF)
    assert account_health.refuses_writes(OFF), "deactivate left the gate open"


async def case_link_prewarm_skips() -> None:
    warmed: list[str] = []

    async def _prewarm(aid):
        warmed.append(aid)

    saved = link_metrics.prewarm, link_metrics._PREWARM_SPREAD_S, account_registry.list_accounts
    link_metrics.prewarm, link_metrics._PREWARM_SPREAD_S = _prewarm, 0.0
    account_registry.list_accounts = lambda: [
        {"id": a, "has_session": True, "platform": "onlyfans"} for a in (OFF, ON)]
    try:
        await link_metrics.prewarm_all()
    finally:
        link_metrics.prewarm, link_metrics._PREWARM_SPREAD_S, account_registry.list_accounts = saved
    assert warmed == [ON], f"prewarmed: {warmed}"


async def case_of_stats_daily_skips() -> None:
    fetched: list[str] = []

    async def _true(*_a, **_k):
        return True

    async def _snapshot(aid, _client, **_k):
        fetched.append(aid)
        return 1

    saved = (of_stats_daily.sample_roster, of_stats_daily._claim, of_stats_daily.snapshot,
             of_stats_daily.client_pool.get, account_registry.get_platform)
    of_stats_daily.sample_roster, of_stats_daily._claim, of_stats_daily.snapshot = _true, _true, _snapshot
    of_stats_daily.client_pool.get = lambda aid: None
    account_registry.get_platform = lambda aid: "onlyfans"
    try:
        await of_stats_daily.tick(pause_s=0)
    finally:
        (of_stats_daily.sample_roster, of_stats_daily._claim, of_stats_daily.snapshot,
         of_stats_daily.client_pool.get, account_registry.get_platform) = saved
    assert OFF not in fetched and ON in fetched, f"fetched: {fetched}"


async def case_pump_never_starts_for_a_deactivated_creator() -> None:
    loaded: list[str] = []
    orig = server._load_client
    server._load_client = lambda aid: loaded.append(aid)
    try:
        await asyncio.wait_for(server._ws_pump_for_account(OFF), timeout=2)
    finally:
        server._load_client = orig
    assert loaded == [], f"a deactivated Creator's pump loaded a client: {loaded}"


async def case_health_all_accounts_skips() -> None:
    probed: list[str] = []

    async def _probe(aid):
        probed.append(aid)
        return {"ok": True}

    orig = server._probe_account
    server._probe_account = _probe
    try:
        out = await server._health_all_accounts()
    finally:
        server._probe_account = orig
    rows = {r["account_id"]: r for r in out["accounts"]}
    assert OFF not in probed and ON in probed, f"probed: {probed}"
    assert rows[OFF]["ok"] is False and rows[OFF]["error"] == "deactivated", rows[OFF]


async def case_pump_supervisor_skips_and_reaps() -> None:
    STARTED.clear()
    STOPPED.clear()
    server._account_pumps[OFF] = asyncio.get_running_loop().create_future()  # a "running" pump
    try:
        await _run_briefly(server._pump_supervisor())
    finally:
        server._account_pumps.pop(OFF, None)
    assert OFF not in STARTED and ON in STARTED, f"started: {STARTED}"
    assert OFF in STOPPED, f"the deactivated Creator's pump was not reaped: {STOPPED}"


async def case_chat_link_seed_skips() -> None:
    enqueued: list[str] = []

    async def _enqueue(aid, kind, payload=None, **_k):
        enqueued.append(aid)

    orig = ax.enqueue_job, ax.wake_supervisor
    ax.enqueue_job, ax.wake_supervisor = _enqueue, lambda: None
    server._chat_links_seeded = False
    try:
        await server._seed_chat_links_once()
    finally:
        ax.enqueue_job, ax.wake_supervisor = orig
    assert OFF not in enqueued and ON in enqueued, f"seeded: {enqueued}"


async def case_ledger_polls_skip() -> None:
    ticked: list[tuple[str, str]] = []

    async def _tick(aid, *, mode="refresh"):
        ticked.append((aid, mode))
        return {}

    async def _fast(aid):
        ticked.append((aid, "fast"))
        return {}

    async def _none(*_a, **_k):
        return None

    async def _false(_aid):
        return False

    async def _refresh(_aid):
        return "refresh"

    async def _zero():
        return 0

    async def _wanted():
        return set(_ACCOUNTS)

    saved = {k: getattr(ti, k) for k in (
        "run_one_tick", "run_fast_tick", "boot_grace", "_is_paused", "_decide_mode",
        "_clear_stale_inflight", "_fast_poll_account_ids")}
    ti.run_one_tick, ti.run_fast_tick, ti.boot_grace = _tick, _fast, _none
    ti._is_paused, ti._decide_mode, ti._clear_stale_inflight = _false, _refresh, _zero
    ti._fast_poll_account_ids = _wanted
    try:
        await _run_briefly(ti.start_supervisor())
        await _run_briefly(ti.start_fast_poll())
    finally:
        for k, v in saved.items():
            setattr(ti, k, v)
    assert sorted(ticked) == sorted([(FOREIGN, "refresh"), (ON, "refresh"), (FOREIGN, "fast"), (ON, "fast")]), \
        f"ticked: {ticked}"


async def case_executor_skips() -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        for aid in (OFF, ON):
            s.add(ScheduledJob(account_id=aid, kind="t_deact_noop", payload_json="{}",
                               status="pending", run_at=now - timedelta(seconds=5)))
    pairs = await ax._due_job_pairs()
    assert (ON, "t_deact_noop") in pairs and (OFF, "t_deact_noop") not in pairs, pairs

    before = CALLS["noop"]
    out = await ax.run_once(OFF, "t_deact_noop")
    assert out == {"status": "skipped", "reason": "account_deactivated"}, out
    assert CALLS["noop"] == before, "automation ran for a deactivated Creator"
    async with get_session() as s:
        status = (await s.execute(select(ScheduledJob.status)
                                  .where(ScheduledJob.account_id == OFF))).scalar_one()
    assert status == "pending", f"the parked job must stay pending, got {status}"


async def case_dead_session_probe_skips() -> None:
    await account_health.mark_session_dead(OFF, "wrong_user")
    await account_health.mark_session_dead(ON, "wrong_user")
    due = await account_health.due_probe_ids(600)
    assert ON in due and OFF not in due, f"due: {due}"
    await account_health.clear_session_dead(OFF)
    await account_health.clear_session_dead(ON)


async def case_reactivate_after_long_gap_backfills() -> None:
    asked: list[tuple[str, datetime | None]] = []

    async def _record(aid, *, since=None):
        asked.append((aid, since))

    orig = ti.trigger_backfill
    ti.trigger_backfill = _record
    owner = _login("/auth/login", "boss")
    try:
        await _backdate_deactivation(OFF, timedelta(days=10))
        r = owner.post(f"/admin/accounts/{OFF}/active", json={"active": True})
        assert r.status_code == 200 and r.json()["is_active"] is True, r.text
        assert not await account_health.is_deactivated(OFF)
        assert len(asked) == 1 and asked[0][0] == OFF, f"backfill asks: {asked}"
        gap = datetime.utcnow() - asked[0][1]
        assert timedelta(days=9) < gap < timedelta(days=11), f"since is not the deactivation: {asked}"

        asked.clear()
        owner.post(f"/admin/accounts/{OFF}/active", json={"active": False})
        await _backdate_deactivation(OFF, timedelta(days=2))
        owner.post(f"/admin/accounts/{OFF}/active", json={"active": True})
        assert asked == [], f"a gap inside the refresh window needs no backfill: {asked}"
    finally:
        ti.trigger_backfill = orig


async def case_reactivate_cancels_jobs_missed_while_off() -> None:
    owner = _login("/auth/login", "boss")
    owner.post(f"/admin/accounts/{OFF}/active", json={"active": False})
    await _backdate_deactivation(OFF, timedelta(days=3))
    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == OFF)
                        .values(status="done"))  # earlier cases' rows
        jobs = {
            "before": ScheduledJob(account_id=OFF, kind="t_deact_noop", payload_json="{}",
                                   status="pending", run_at=now - timedelta(days=4)),
            "missed": ScheduledJob(account_id=OFF, kind="t_deact_noop", payload_json="{}",
                                   status="pending", run_at=now - timedelta(days=1)),
            "future": ScheduledJob(account_id=OFF, kind="t_deact_noop", payload_json="{}",
                                   status="pending", run_at=now + timedelta(hours=1)),
            "other": ScheduledJob(account_id=ON, kind="t_deact_noop", payload_json="{}",
                                  status="pending", run_at=now - timedelta(days=1)),
            "cleanup": ScheduledJob(account_id=OFF, kind="unsend_messages", payload_json="{}",
                                    status="pending", run_at=now - timedelta(days=1)),
        }
        s.add_all(jobs.values())
        await s.flush()
        ids = {k: j.id for k, j in jobs.items()}
    r = owner.post(f"/admin/accounts/{OFF}/active", json={"active": True})
    assert r.status_code == 200, r.text
    async with get_session() as s:
        got = {k: await s.get(ScheduledJob, i) for k, i in ids.items()}
    assert got["missed"].status == ax.JOB_CANCELLED, got["missed"].status
    assert got["missed"].last_error == ax.MISSED_WHILE_OFF_REASON, got["missed"].last_error
    for k in ("before", "future", "other", "cleanup"):
        assert got[k].status == "pending", f"{k}: {got[k].status}"


async def case_trigger_backfill_reopens_the_window() -> None:
    async with get_session() as s:
        s.add(TransactionScanHistory(
            account_id=ON, fully_backfilled=True, current_status="ok",
            oldest_seen_occurred_at=datetime.utcnow() - timedelta(days=90),
            backfill_floor=datetime.utcnow() - timedelta(days=90),
        ))
    since = datetime.utcnow() - timedelta(days=20)
    await ti.trigger_backfill(ON, since=since)
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ON)
    assert row.fully_backfilled is False and row.current_status == "idle", row.current_status
    start, end = ti._window_for("backfill", row)
    assert start == since and datetime.utcnow() - end < timedelta(minutes=1), (start, end)


_harness.run()
