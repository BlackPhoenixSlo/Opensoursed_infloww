from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import _harness
from _send_kill_cell import AID, SYNC_URL, Check, FakeHttp, cells, client, err, post, restart

AID2 = "900539700124344778"
KIND = "hold_probe"
ACCOUNTS = f"onlyfans:{AID},onlyfans:{AID2}"
OWNER = "hold_owner"
_fans = iter(range(74001, 75000))


def _db(sql: str, args: tuple = ()):
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return c.execute(sql, args).fetchall()


def _table() -> bool:
    return bool(_db("SELECT 1 FROM sqlite_master WHERE name='cell_holds'"))


def _holds() -> list[tuple]:
    return _db("SELECT platform, account, why, scope, blocks, op, released_by IS NOT NULL FROM cell_holds ORDER BY id")


_wire: dict = {}


def _probe():
    async def run(account_id, payload, run_id=None):
        import send_ops
        import server
        http, fan = _wire["http"], _wire["fan"]
        c = client(http)
        text = f"probe {payload.get('n', 0)}"
        if not server._CELLS:
            await asyncio.to_thread(c.send_message, fan, text)
        else:
            op = send_ops.op_id("onlyfans", account_id, "composer", str(fan), f"probe-{run_id}")
            await asyncio.to_thread(send_ops.dispatch, "onlyfans", account_id, op, "composer", str(fan),
                                    send_ops.digest(text), lambda: c.send_message(fan, text))
        return {"sent": 1}
    return run


@contextlib.contextmanager
def _executor(on: bool):
    import automation_executor as ax
    real = ax.get_automation
    with patch.object(ax, "_CELLS", on), \
            patch.object(ax, "get_automation", lambda k: _probe() if k == KIND else real(k)):
        yield ax


def _fresh() -> tuple[FakeHttp, int]:
    _wire.update(http=FakeHttp(), fan=next(_fans))
    return _wire["http"], _wire["fan"]


async def _seed() -> dict[str, int]:
    from db.engine import get_session
    from db.models import Account, AccountAiConfig, AutomationRule, Chatter, ChatterUser, ScheduledJob, User, UserAccount
    now = datetime.utcnow()
    past, future = now - timedelta(minutes=5), now + timedelta(hours=1)
    async with get_session() as s:
        for aid in (AID, AID2):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid, nickname=aid))
        s.add(User(id="u_hold", username=OWNER, password=OWNER, is_admin=True))
        s.add(Chatter(id="c_hold", username="hold_chatter", password="hold_chatter", display_name="Hold chatter"))
        await s.flush()
        s.add(ChatterUser(chatter_id="c_hold", user_id="u_hold"))
        s.add_all(UserAccount(user_id="u_hold", account_id=aid) for aid in (AID, AID2))
        s.add(AccountAiConfig(account_id=AID, utc_offset=0))
        rule = AutomationRule(account_id=AID, name=KIND, kind=KIND, trigger_json=json.dumps({"every_seconds": 60, "tz_offset_minutes": 0}),
                              quiet_hours_json=json.dumps([0, 24]),
                              steps_json="{}", is_enabled=True)
        s.add(rule)
        await s.flush()
        jobs = {
            "due_one_shot": ScheduledJob(account_id=AID, kind="scheduled_send", payload_json="{}", run_at=past),
            "tagged_full_ai": ScheduledJob(account_id=AID, kind="full_ai_chat", run_at=past,
                                            payload_json=json.dumps({"_rule_id": rule.id})),
            "running_mass": ScheduledJob(account_id=AID, kind="mass_premade", payload_json="{}", run_at=past,
                                         status="running"),
            "due_rule": ScheduledJob(account_id=AID, kind=KIND, payload_json="{}", run_at=past, rule_id=rule.id,
                                     created_at=now - timedelta(minutes=10)),
            "future_one_shot": ScheduledJob(account_id=AID, kind="scheduled_send", payload_json="{}", run_at=future),
            "due_other": ScheduledJob(account_id=AID2, kind="scheduled_send", payload_json="{}", run_at=past),
        }
        s.add_all(jobs.values())
        await s.flush()
        return {"rule": rule.id, **{k: j.id for k, j in jobs.items()}}


def _jobs(ids) -> dict[int, tuple]:
    rows = _db(f"SELECT id, status, last_error FROM scheduled_jobs WHERE id IN ({','.join('?' * len(ids))})",
               tuple(ids))
    return {r[0]: (r[1], r[2]) for r in rows}


def _rule_jobs(rule_id: int) -> list[tuple]:
    return _db("SELECT id, status, last_error FROM scheduled_jobs WHERE rule_id=? ORDER BY id", (rule_id,))


def _snapshot(dest: Path) -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as src, \
            contextlib.closing(sqlite3.connect(str(dest))) as out:
        src.backup(out)


def _restore(snap: Path) -> None:
    with contextlib.closing(sqlite3.connect(str(snap))) as src, \
            contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as out:
        src.backup(out)
        out.execute("UPDATE cell_meta SET data_gen=data_gen+1")
        out.commit()


async def _boot() -> list:
    import cell_hold
    import cell_mode
    restart()
    cell_mode.install_meta(SYNC_URL)
    return await cell_hold.boot(SYNC_URL)


async def env_unset() -> list[Check]:
    import cell_hold
    http, _ = _fresh()
    boom = AssertionError("cell_hold touched with the env unset")
    with cells(on=False), _executor(False) as ax, \
            patch.object(cell_hold, "held", side_effect=boom), patch.object(cell_hold, "holds", side_effect=boom), \
            patch.object(cell_hold, "blocking", side_effect=boom):
        got = await ax.run_once(AID, KIND, payload={"n": 0})
        pairs = await ax._due_job_pairs()
    return [("env unset: executor never consults cell_hold; automation sends 1 accept, no cell_holds table",
             got.get("status") == "ok" and len(http.accepts) == 1 and not _table() and isinstance(pairs, list),
             {"got": got, "calls": http.calls, "table": _table()})]


async def restore(tmp: Path) -> list[Check]:
    import actor_token
    import cell_hold
    import cell_mode
    import run_decide
    import send_ops
    import server
    import system_admin_api
    out: list[Check] = []
    ids = await _seed()
    with cells(accounts=ACCOUNTS), _executor(True) as ax, patch.object(server, "actor_token", actor_token, create=True):
        restored = await _boot()
        out.append(("same Data generation on boot → no hold", restored == [] and not cell_hold.holds(),
                    {"restored": restored, "holds": _holds()}))
        snap = tmp / "pre-claim.db"
        _snapshot(snap)
        gen = cell_mode.data_gen()
        fan = next(_fans)
        st, _ = await post(FakeHttp(), fan, "after-copy")
        out.append(("claim made after the copy", st == 200, {"status": st}))
        _restore(snap)
        restored = await _boot()
        rows = _holds()
        op = f"data_gen {gen}->{gen + 1}"
        want = [("onlyfans", a, "restore", "creator", "automations", op, 0) for a in sorted((AID, AID2))]
        out.append(("pre-claim copy + Data generation +1 → one restore hold row per Creator",
                    sorted(restored) == [("onlyfans", a) for a in sorted((AID, AID2))] and sorted(rows) == want,
                    {"restored": restored, "rows": rows}))

        jobs = _jobs([v for k, v in ids.items() if k != "rule"])
        parked = ("error", run_decide.RESTORE_REASON)
        occ = [r for r in _rule_jobs(ids["rule"]) if r[0] != ids["due_rule"]]
        out.append(("due one-shot, running, rule job and the recurring occurrence due at boot parked 'may have "
                    "sent (restore)' on every Creator; future job stays pending",
                    all(jobs[ids[k]] == parked for k in ("due_one_shot", "tagged_full_ai", "running_mass", "due_rule", "due_other"))
                    and jobs[ids["future_one_shot"]] == ("pending", None)
                    and len(occ) == 1 and occ[0][1:] == parked, {"jobs": jobs, "occurrences": occ}))
        listed = await system_admin_api.system_runs(limit=500, kind=None, account_id=AID, status="error")
        restore_ids = {j["id"] for j in listed["jobs"] if j["last_error"] == run_decide.RESTORE_REASON}
        out.append(("parked jobs listed via /admin/system/runs",
                    {ids["due_one_shot"], ids["running_mass"], ids["due_rule"], occ[0][0] if occ else -1}
                    <= restore_ids, {"listed": sorted(restore_ids)}))

        http, _ = _fresh()
        tick = await ax.run_once(AID, KIND, payload={"n": 1})
        pairs = await ax._due_job_pairs()
        mat = await ax._materialize_due_rules()
        notes = _db("SELECT stats_json FROM automation_runs WHERE account_id=? AND status='skipped'"
                    " AND json_extract(stats_json, '$.reason')='cell_held'", (AID,))
        out.append(("repeated held ticks leave one skipped Cell-held run",
                    len(notes) == 1 and json.loads(notes[0][0]).get("reason") == "cell_held", {"runs": notes}))
        out.append(("held Creator: automated tick refused cell_held, 0 transport calls; due pairs + rule "
                    "materialisation skip it",
                    (tick.get("status"), tick.get("reason"), tick.get("why")) == ("skipped", "cell_held", "restore")
                    and not http.calls and not [p for p in pairs if str(p[0]) in (AID, AID2)] and mat == 0,
                    {"tick": tick, "calls": http.calls, "pairs": pairs, "materialised": mat}))

        from of_write import _RUN_WRITE
        import platforms
        fan = next(_fans)
        op = send_ops.op_id("onlyfans", AID, "composer", str(fan), "held")
        order = []
        tok = _RUN_WRITE.set(run_decide.RunWrites())
        try:
            for gates in (("owner", "cap"), ("cap",), ()):
                with contextlib.ExitStack() as stack:
                    if "owner" in gates:
                        stack.enter_context(patch.dict("os.environ", {"OI_ACCOUNTS": f"onlyfans:{AID2}"}))
                    if "cap" in gates:
                        stack.enter_context(patch.object(platforms, "refusal_for_account", lambda a, n: "lacks"))
                    try:
                        send_ops.dispatch("onlyfans", AID, op, "composer", str(fan), "d", lambda: http.calls.append(1))
                        order.append("sent")
                    except (send_ops.SendRefused, cell_hold.CellHeld) as e:
                        order.append(send_ops.refusal_reason(e))
        finally:
            _RUN_WRITE.reset(tok)
        claim = _db("SELECT 1 FROM send_ops WHERE account=? AND op_id=?", (AID, op))
        out.append(("automated dispatch gate order: not_owner → capability → cell_held, 0 transport calls, no claim",
                    order == ["not_owner", "capability", "cell_held"] and not http.calls and not claim,
                    {"order": order, "calls": http.calls, "claim": claim}))
        st, body = await post(FakeHttp(), next(_fans), "manual-while-held")
        out.append(("manual composer send carries on while held", st == 200, {"status": st, "body": body}))

        again = await _boot()
        out.append(("one more restart: hold still there, no duplicate rows", again == [] and _holds() == rows,
                    {"again": again, "rows": _holds()}))

        import httpx
        if not any(getattr(r, "path", None) == "/admin/cell-holds/release" for r in server.app.routes):
            server.app.include_router(cell_hold.router)
        before = _db("SELECT COUNT(*) FROM actions WHERE action='POST /admin/cell-holds/release'")[0][0]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as c:
            anonymous = await c.post("/admin/cell-holds/release", params={"account_id": AID})
            chatter_login = await c.post("/chatter/login",
                                         json={"username": "hold_chatter", "password": "hold_chatter"})
            chatter_release = await c.post("/admin/cell-holds/release", params={"account_id": AID})
            c.cookies.clear()
            login = await c.post("/auth/login", json={"username": OWNER, "password": OWNER})
            unconfirmed = await c.get("/admin/unconfirmed-sends", params={"account_id": AID})
            stale = await c.post("/admin/cell-holds/release", params={"account_id": AID, "op": "old"})
            r = await c.post("/admin/cell-holds/release", params={"account_id": AID})
            stray = await c.post("/admin/cell-holds/release", params={"account_id": "1"})
        out.append(("unconfirmed sends list includes the Creator's open restore hold",
                    unconfirmed.status_code == 200
                    and [h["op"] for h in unconfirmed.json().get("restore_holds", [])] == [rows[0][5]],
                    {"status": unconfirmed.status_code, "body": unconfirmed.text}))
        audit = _db("SELECT account_id FROM actions WHERE action='POST /admin/cell-holds/release'")[before:]
        released = _db("SELECT released_by FROM cell_holds WHERE account=? AND released_at IS NOT NULL", (AID,))
        out.append(("release one Creator via route: audited (actions row + released_by), other Creator still held",
                    login.status_code == r.status_code == 200 and r.json() == {"released": 1, "held": None} and audit[-1:] == [(AID,)] and anonymous.status_code in (401, 403)
                    and chatter_login.status_code == 200 and chatter_release.status_code == 403
                    and stale.status_code == 200 and stale.json()["released"] == 0
                    and released == [(f"user:u_hold:{OWNER}",)] and cell_hold.held(AID2) is not None
                    and cell_hold.held(AID) is None and stray.status_code in (403, 409),
                    {"status": r.status_code, "body": r.text, "audit": audit, "released": released,
                     "stray": [stray.status_code, stray.text], "chatter": [chatter_login.status_code, chatter_release.status_code]}))

        from db.engine import get_session
        from db.models import ScheduledJob
        async with get_session() as s:
            s.add(ScheduledJob(account_id=AID, kind=KIND, payload_json='{"n": 2}',
                               run_at=datetime.utcnow() - timedelta(seconds=1)))
        http, fan = _fresh()
        sent = await ax.run_once(AID, KIND)
        other = await ax.run_once(AID2, KIND, payload={"n": 3})
        after = _jobs([v for k, v in ids.items() if k != "rule"])
        out.append(("released Creator's next automation sends once (1 accept + sent row); parked jobs stay parked; "
                    "other Creator still refused cell_held",
                    sent.get("status") == "ok" and len(http.accepts) == 1
                    and _db("SELECT state FROM send_ops WHERE account=? AND op_id=?", (AID, send_ops.op_id(
                        "onlyfans", AID, "composer", str(fan), f"probe-{sent.get('run_id')}"))) == [("sent",)]
                    and all(after[ids[k]] == parked for k in ("due_one_shot", "tagged_full_ai", "running_mass", "due_rule", "due_other"))
                    and other.get("reason") == "cell_held",
                    {"sent": sent, "other": other, "accepts": len(http.accepts), "jobs": after}))
    return out


async def run_all(tmp: Path) -> list[Check]:
    checks = await env_unset()
    return checks + await restore(tmp)
