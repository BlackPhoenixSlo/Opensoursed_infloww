from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException

import _send_kill_cell as cell
from _send_kill import db_row

AID = cell.AID
KIND = "pause_probe"
_dir = tempfile.mkdtemp(prefix="oi_permit_")
PERMIT = os.path.join(_dir, "send_permit")


def write_permit(raw: str | dict | None) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(PERMIT)
    if raw is not None:
        with open(PERMIT, "w") as fh:
            fh.write(raw if isinstance(raw, str) else json.dumps(raw))


def fresh() -> dict:
    return {"lease_id": "L1", "box": "b1", "until": time.time() + 600}


BAD: dict[str, str | dict | None] = {
    "missing": None,
    "unreadable": "{not json",
    "other Box": {"lease_id": "L1", "box": "b2", "until": time.time() + 600},
    "expired": {"lease_id": "L1", "box": "b1", "until": time.time() - 1},
    "no until": {"lease_id": "L1", "box": "b1"},
}


@contextlib.contextmanager
def permit_env(on: bool = True):
    keys = ("OI_CELL_SEND_PERMIT", "OI_CELL_INSTANCE")
    values = dict(zip(keys, (PERMIT, "b1:2"))) if on else {}
    with cell.environment(*(() if on else keys), **values), cell.cells():
        yield


def _like(http: cell.FakeHttp) -> str:
    import server
    try:
        server._proxy_message_write(lambda: cell.client(http).like_message(7))
    except HTTPException as e:
        return cell.err(e.detail) or str(e.status_code)
    return "ok"


def _job(aid: str) -> tuple | None:
    return db_row("SELECT status, attempts FROM scheduled_jobs WHERE account_id=? AND kind=? ORDER BY id DESC",
                  (aid, KIND))


async def _seed_job(aid: str) -> None:
    from db.engine import get_session
    from db.models import ScheduledJob
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind=KIND, payload_json="{}", status="pending",
                           run_at=datetime.utcnow() - timedelta(minutes=1)))


def _plugin(http: cell.FakeHttp, fan: int, before=None, after=None, anchor="j1"):
    import send_ops

    async def fn(account_id, payload, *, run_id=None):
        if before:
            before()
        c = cell.client(http)
        import automation_executor as ax

        def send():
            return send_ops.dispatch(
                "onlyfans", account_id, send_ops.op_id("onlyfans", account_id, KIND, str(fan), anchor),
                KIND, str(fan), send_ops.digest({"anchor": "j1"}), lambda: c.send_message(fan, "hi"))

        with patch.dict(send_ops.CAPABILITY, {KIND: "send_message"}):
            await ax.of_write_paced(account_id, send, send_purpose="manual", min_gap_s=0, tries=1)
        if after:
            after()
        return {"sent": 1}
    return fn


async def _run(fn) -> dict:
    import automation_executor as ax
    with patch.object(ax, "get_automation", lambda k: fn if k == KIND else None), \
            patch.object(ax.run_decide, "sends_once", lambda k: k == KIND):
        return await ax.run_once(AID, KIND)


async def composer() -> list[cell.Check]:
    out: list[cell.Check] = []
    with permit_env():
        for name, raw in BAD.items():
            write_permit(raw)
            fan, http = next(cell._fans), cell.FakeHttp()
            st, body = await cell.post(http, fan, f"paused-{fan}")
            bare = cell.FakeHttp()
            st2, body2 = await cell.post(bare, fan, None)
            like = cell.FakeHttp()
            liked = _like(like)
            out.append((f"permit {name}: composer 503 writes_paused, no claim row, 0 calls; no-op-id send and like"
                        " refused too", (st, cell.err(body)) == (503, "writes_paused")
                        and cell.row(fan, f"paused-{fan}") is None and not http.calls
                        and (st2, cell.err(body2)) == (503, "writes_paused") and not bare.calls
                        and liked == "writes_paused" and not like.calls,
                        {"answer": [st, body], "row": cell.row(fan, f"paused-{fan}"), "calls": http.calls,
                         "bare": [st2, body2, bare.calls], "like": [liked, like.calls]}))
        write_permit(fresh())
        fan, http = next(cell._fans), cell.FakeHttp()
        st, _ = await cell.post(http, fan, f"fresh-{fan}")
        r = cell.row(fan, f"fresh-{fan}")
        out.append(("fresh permit: composer goes out once, sent row", st == 200 and len(http.accepts) == 1
                    and r is not None and r["state"] == "sent", {"status": st, "row": r, "calls": http.calls}))
    with permit_env():
        import server
        write_permit(BAD["expired"])
        http = cell.FakeHttp()
        req = cell.request({})
        with cell.route(req, cell.client(http)):
            try:
                await server.of_schedule_message(next(cell._fans), req,
                                                 server._ScheduleMessageBody(text="later", scheduled_date="2000-01-01T12:00:00Z"))
            except HTTPException as e:
                st, body = e.status_code, e.detail
            else:
                st, body = 200, {}
        out.append(("unanchored native schedule honors lapsed permit",
                    (st, cell.err(body)) == (503, "writes_paused") and not http.calls,
                    {"answer": [st, body], "calls": http.calls}))
    with permit_env(on=False):
        write_permit(None)
        fan, http = next(cell._fans), cell.FakeHttp()
        st, _ = await cell.post(http, fan, f"unset-{fan}")
        out.append(("env unset: no permit check, send goes out with no file", st == 200 and len(http.accepts) == 1,
                    {"status": st, "calls": http.calls}))
    with permit_env():
        write_permit(fresh())
        from of_client import OFClient
        prepare = OFClient.prepare_message

        def lapse(client, *args, **kwargs):
            result = prepare(client, *args, **kwargs)
            write_permit(BAD["expired"])
            return result

        fan, http = next(cell._fans), cell.FakeHttp()
        with patch.object(OFClient, "prepare_message", lapse):
            st, body = await cell.post(http, fan, "permit-lapsed-after-claim")
        r = cell.row(fan, "permit-lapsed-after-claim")
        out.append(("permit lapses after claim: 503 writes_paused, refused row, zero wire calls",
                    (st, cell.err(body)) == (503, "writes_paused") and r["state"] == "refused" and not http.calls,
                    {"answer": [st, body], "row": r, "calls": http.calls}))
    return out


async def automation() -> list[cell.Check]:
    import automation_executor as ax
    import dm_rate
    from _send_kill import seed_account
    out: list[cell.Check] = []
    await seed_account(AID)
    await _seed_job(AID)
    fan = next(cell._fans)
    dm_rate._reset()
    with permit_env():
        write_permit(BAD["expired"])
        drained: list = []

        async def spy(*_, **__):
            drained.append(1)
            return []
        with patch.object(ax, "_due_job_pairs", spy), patch.object(ax, "_materialize_due_rules", spy):
            await ax._drain_due_jobs_once()
            held = list(drained)
            write_permit(fresh())
            await ax._drain_due_jobs_once()
        out.append(("lapsed permit: executor tick returns before reading due jobs; fresh permit reads them",
                    not held and len(drained) == 2, {"paused": held, "fresh": drained}))

        write_permit(BAD["expired"])
        h0 = cell.FakeHttp()
        r0 = await _run(_plugin(h0, fan))
        stored = db_row("SELECT status FROM automation_runs WHERE id=?", (r0.get("run_id"),))
        out.append(("lapsed permit: no skip row before claim; job pending, attempts 0",
                    r0.get("reason") == "writes_paused" and "run_id" not in r0 and stored is None
                    and _job(AID) == ("pending", 0) and not h0.calls,
                    {"run": r0, "job": _job(AID), "calls": h0.calls, "stored": stored}))

        write_permit(fresh())
        h1 = cell.FakeHttp()
        r1 = await _run(_plugin(h1, fan, before=lambda: write_permit(BAD["expired"])))
        out.append(("permit lapses mid-run: job released to pending, attempts unchanged, 0 calls",
                    r1.get("reason") == "writes_paused" and _job(AID) == ("pending", 0) and not h1.calls,
                    {"run": r1, "job": _job(AID), "calls": h1.calls}))

        write_permit(fresh())
        h2 = cell.FakeHttp()
        r2 = await _run(_plugin(h2, fan))
        r3 = await _run(_plugin(h2, fan))
        out.append(("permit back: queued job runs once (1 accept, done); next tick no_job",
                    r2.get("status") == "ok" and _job(AID) == ("done", 1) and len(h2.accepts) == 1
                    and r3.get("reason") == "no_job", {"run": r2, "again": r3, "job": _job(AID),
                                                        "calls": h2.calls}))

        def refused():
            import send_ops
            raise send_ops.SendRefused(503, "writes_paused")

        await _seed_job(AID)
        h3 = cell.FakeHttp()
        r4 = await _run(_plugin(h3, next(cell._fans), after=refused, anchor="partial"))
        out.append(("refusal after partial delivery parks the job",
                    r4.get("status") == "error" and _job(AID) == ("error", 1) and len(h3.accepts) == 1,
                    {"run": r4, "job": _job(AID), "calls": h3.calls}))
    return out


async def run() -> list[cell.Check]:
    return [*await composer(), *await automation()]


async def case_single_box_ignores_leftover_permit():
    import server

    await cell._seed()
    write_permit(None)
    req = cell.request({"x-op-id": "single-box-leftover-permit"})
    http = cell.FakeHttp()
    with cell.cells(on=False), cell.environment(OI_CELL_SEND_PERMIT=PERMIT, OI_CELL_INSTANCE="b1:2"):
        with cell.route(req, cell.client(http)):
            await server.of_schedule_message(next(cell._fans), req, server._ScheduleMessageBody(
                text="later", scheduled_date="2099-01-01T12:00:00Z"))
    assert len(http.accepts) == 1, http.calls
