from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sqlite3
import types
from unittest.mock import patch

from fastapi import HTTPException

import _harness
from _send_kill import Killed, _durable_send_state
from _send_kill_cell import AID, FakeHttp, accept, cells, client, err, restart as cell_restart, status

KINDS = ("manual_mass_send", "manual_mass_schedule", "native_schedule", "publish_now", "vault_send")
LATER = "2099-01-01T10:00:00+00:00"
_fans = iter(range(74001, 75000))
_sids = iter(range(5001, 6000))
Check = tuple[str, bool, dict]


def _req(headers: dict):
    return types.SimpleNamespace(method="POST", query_params={}, state=types.SimpleNamespace(),
                                 headers={"x-account-id": AID, **headers})


def _op_headers(anchor: str | None, part: int) -> dict:
    return {**({"x-op-id": anchor} if anchor else {}), **({"x-op-part": str(part)} if part else {})}


@contextlib.contextmanager
def _route(req, http: FakeHttp):
    import server
    tok = server._request_ctx.set(req)
    try:
        with patch.object(server, "_load_client", return_value=_vault_client(http)):
            yield
    finally:
        server._request_ctx.reset(tok)


def _vault_client(http: FakeHttp):
    import of_client
    from pathlib import Path
    c = client(http)
    c.upload_claim = lambda path: of_client.UploadClaim(
        media={"processId": f"p-{Path(path).name}"}, dedupe_key=Path(path).name, size=16)
    c.get_user = lambda handle: {"id": int(handle.removeprefix("fan")), "username": handle, "name": handle}
    return c


async def _answer(coro):
    try:
        return 200, await coro
    except HTTPException as e:
        return e.status_code, e.detail


async def send(kind: str, http: FakeHttp, target: int, anchor: str | None, *, part: int = 0,
               text: str = "hello all", unsend: int | None = None):
    import mass_queue_api as mq
    import server
    req = _req(_op_headers(anchor, part))
    with _route(req, http):
        if kind in ("manual_mass_send", "manual_mass_schedule"):
            body = mq._MassScheduleBody(text=text, user_ids=[target], unsend_after_hours=unsend,
                                        scheduled_date=LATER if kind == "manual_mass_schedule" else None)
            return await _answer(mq.of_send_or_schedule_mass(req, body))
        if kind == "native_schedule":
            return await _answer(server.of_schedule_message(
                target, req, server._ScheduleMessageBody(text=text, scheduled_date=LATER)))
        if kind == "publish_now":
            return await _answer(asyncio.to_thread(server.of_publish_schedule, target))
        return await _answer(_vault(req, target))


async def _vault(req, fan: int):
    import auth
    import server
    import of_write
    import vault_import_api
    import vault_upload
    from starlette.datastructures import Headers, UploadFile
    from _send_kill_http import _vault_spool
    _vault_spool()
    of_write._write_gates.pop(AID, None)
    spawned: list = []
    f = UploadFile(file=io.BytesIO(b"x" * 16), filename=f"v{fan}.jpg", headers=Headers({"content-type": "image/jpeg"}))
    tok = auth._request_user.set(auth.AuthedUser("u_manual", "manual_owner", frozenset({AID})))
    try:
        with patch.object(server, "_spawn_bg", lambda coro, name: spawned.append(coro)):
            out = await vault_import_api.of_vault_upload_batch(
                req, files=[f], drive_links="", list_id="", meta="", fan_username=f"fan{fan}",
                fan_id=str(fan), keep_open=False)
            for coro in spawned:
                await coro
    finally:
        auth._request_user.reset(tok)
    return {"batch": out, "item": (vault_upload.latest_run(AID) or {}).get("items", [{}])[0]}


def vault_accept(fake: FakeHttp, url: str, body: dict):
    r = accept(fake, url, body)
    fake.accepts[-1]["media"] = [{"id": 901, "isReady": True}]
    r._body["media"] = fake.accepts[-1]["media"]
    return r


def anchor_of(kind: str, target: int, anchor: str | None) -> str:
    return str(target) if kind == "publish_now" else anchor or ""


def rows(kind: str, target: int, anchor: str | None = None, part: int | None = None) -> list[dict]:
    import send_ops
    tgt = "mass" if kind.startswith("manual_mass") else str(target)
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        try:
            got = c.execute("SELECT op_id, state, attempts, result FROM send_ops WHERE account=? AND kind=? AND target=?"
                            " ORDER BY created_at", (AID, kind, tgt)).fetchall()
        except sqlite3.OperationalError:
            return []
    if anchor is not None or kind == "publish_now":
        want = {send_ops.op_id("onlyfans", AID, kind, tgt, anchor_of(kind, target, anchor), p)
                for p in ([part] if part is not None else range(8))}
        got = [r for r in got if r[0] in want]
    return [{"state": s, "attempts": a, "result": json.loads(r) if r else None} for _o, s, a, r in got]


def wire_calls(http: FakeHttp) -> list:
    return [c[:2] for c in http.calls if c[0] != "GET"]


def restart() -> int:
    import mass_queue_api as mq
    mq._send_keys.clear()
    return cell_restart()


def _step(kind: str):
    return vault_accept if kind == "vault_send" else accept


def _target(kind: str) -> int:
    return next(_sids) if kind == "publish_now" else next(_fans)


def _unsend_jobs() -> int:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return c.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE account_id=? AND kind='unsend_messages'",
                         (AID,)).fetchone()[0]


async def clean(kind: str) -> list[Check]:
    target, anchor = _target(kind), f"clean-{kind}"
    http = FakeHttp(_step(kind))
    st, body = await send(kind, http, target, anchor)
    r = rows(kind, target, anchor if kind != "vault_send" else None)
    out: list[Check] = [(f"{kind}: clean run = 1 accept + 1 sent row", st == 200 and len(http.accepts) == 1
                         and len(wire_calls(http)) == 1 and [x["state"] for x in r] == ["sent"],
                         {"status": st, "body": body, "calls": http.calls, "rows": r})]
    if kind == "vault_send":
        out.append(("vault: item landed with the sent message", isinstance(body, dict)
                    and body["item"].get("message_id") == http.accepts[0]["id"], {"body": body}))
        return out
    before = _durable_send_state(AID)
    st2, body2 = await send(kind, http, target, anchor)
    out.append((f"{kind}: replay returns the same body, 0 wire calls, no new local rows",
                st2 == 200 and body2 == body and len(wire_calls(http)) == 1 and _durable_send_state(AID) == before
                and rows(kind, target, anchor)[0]["attempts"] == 1,
                {"first": body, "replay": [st2, body2], "calls": http.calls}))
    return out


async def mass_side_effects() -> list[Check]:
    fan = next(_fans)
    http = FakeHttp()
    st, body = await send("manual_mass_send", http, fan, "unsend", unsend=2)
    jobs, state = _unsend_jobs(), _durable_send_state(AID)
    st2, body2 = await send("manual_mass_send", http, fan, "unsend", unsend=2)
    return [("mass replay: same body; mass-run, unsend-enqueue and attribution rows byte-identical",
             st == st2 == 200 and body2 == body and isinstance(body, dict) and body.get("_auto_unsend_job_id")
             and body.get("_mass_run_id") and _unsend_jobs() == jobs and _durable_send_state(AID) == state
             and len(http.accepts) == 1, {"first": [st, body], "replay": [st2, body2], "jobs": jobs})]


async def mass_gifs() -> list[Check]:
    fan = next(_fans)
    http = FakeHttp()
    texts = ("hello all", "", "")
    answers = [await send("manual_mass_send", http, fan, "gifs", part=i, text=t) for i, t in enumerate(texts)]
    r = rows("manual_mass_send", fan, "gifs")
    out: list[Check] = [("manual mass + 2 extra GIFs: 3 parts, each accepted once",
                         all(st == 200 for st, _ in answers) and len(http.accepts) == 3
                         and [x["state"] for x in r] == ["sent"] * 3, {"answers": answers, "rows": r})]
    again = [await send("manual_mass_send", http, fan, "gifs", part=i, text=t) for i, t in enumerate(texts)]
    out.append(("manual mass + 2 GIFs resubmit: 0 more sends, each part replays its own body",
                len(http.accepts) == 3 and [b for _, b in again] == [b for _, b in answers],
                {"again": again, "accepts": len(http.accepts)}))
    st, body = await send("manual_mass_send", http, fan, "gifs", part=1, text="a different gif")
    out.append(("same op + part, different body → op_conflict, 0 wire calls",
                (st, err(body)) == (409, "op_conflict") and len(http.accepts) == 3, {"answer": [st, body]}))
    st, body = await send("manual_mass_send", http, fan, "gifs", part="x")  # type: ignore[arg-type]
    out.append(("non-numeric X-Op-Part → 400, 0 wire calls", st == 400 and len(http.accepts) == 3,
                {"answer": [st, body]}))
    return out


async def refused_resubmit(kind: str) -> list[Check]:
    target, anchor = _target(kind), f"refused-{kind}"
    http = FakeHttp(status(400))
    st, body = await send(kind, http, target, anchor)
    r1 = rows(kind, target, anchor)
    st2, body2 = await send(kind, http, target, anchor)
    return [(f"{kind}: full OF 4xx → refused; same-op resubmit re-claims, sends once",
             st != 200 and [x["state"] for x in r1] == ["refused"] and st2 == 200 and len(http.accepts) == 1
             and [x["state"] for x in rows(kind, target, anchor)] == ["sent"],
             {"first": [st, body], "rows": r1, "resubmit": [st2, body2]})]


async def pre_wire_refusal() -> list[Check]:
    fan = next(_fans)
    http = FakeHttp()
    import audiences

    async def unknown(*_a, **_k):
        raise audiences.AudienceUnknown("list read failed")
    with patch.object(audiences, "resolve_mass_audience", unknown):
        st, body = await send("manual_mass_send", http, fan, "prewire")
    r = rows("manual_mass_send", fan, "prewire")
    st2, _ = await send("manual_mass_send", http, fan, "prewire")
    return [("mass 422 before the wire → refused, 0 wire; same op re-claims and sends once",
             st == 422 and [x["state"] for x in r] == ["refused"] and st2 == 200 and len(http.accepts) == 1,
             {"first": [st, body], "rows": r, "resubmit": st2})]


async def unclaimed() -> list[Check]:
    out: list[Check] = []
    for kind in ("manual_mass_send", "manual_mass_schedule", "native_schedule"):
        target = next(_fans)
        http = FakeHttp()
        st, body = await send(kind, http, target, None)
        out.append((f"{kind}: no X-Op-Id in Cell mode → unclaimed_send, 0 wire calls",
                    (st, err(body)) == (409, "unclaimed_send") and not wire_calls(http),
                    {"answer": [st, body], "calls": http.calls}))
    return out


async def post_now() -> list[Check]:
    sid = next(_sids)
    http = FakeHttp()
    st, body = await send("publish_now", http, sid, None)
    st2, _ = await send("publish_now", http, sid, None)
    return [("Post now (feed post) works in Cell mode, untripped; a second press replays, 0 more sends",
             st == st2 == 200 and wire_calls(http) == [("PUT", f"/schedules/{sid}/publish")]
             and len(http.accepts) == 1, {"answer": [st, body], "calls": http.calls})]


def _ten_seconds(fake, url, body):
    from _send_kill_cell import Resp
    return Resp(400, {"error": {"code": 0, "message": "Please allow 10 seconds between messages"}}, url)


async def vault_retry_replays() -> list[Check]:
    import automation_executor as ax
    import relay_host
    from of_write import of_write_with_retry
    fan = next(_fans)
    http = FakeHttp(_ten_seconds, vault_accept)
    recorded: list = []
    real = relay_host.record_fan_send

    async def spy(*a, **k):
        recorded.append(a[1])
        return await real(*a, **k)

    async def quick(fn, *, tries=2, pause_s=0):
        return await of_write_with_retry(fn, tries=tries, pause_s=0)
    with patch.object(relay_host, "record_fan_send", spy), patch.object(ax, "of_write_with_retry", quick):
        st, body = await send("vault_send", http, fan, None)
    r = rows("vault_send", fan)
    return [("vault: OF's 10 s refusal then a retry stays one op; 1 accept, 1 fan-send record",
             st == 200 and len(http.accepts) == 1 and [x["state"] for x in r] == ["sent"] and recorded == [fan],
             {"answer": [st, body], "rows": r, "recorded": recorded, "calls": http.calls})]


def _after_wire_patch(kind: str, at_kill: dict, probe):
    import mass_queue_api as mq
    import relay_host
    import send_ops

    async def die_async(*_a, **_k):
        at_kill["row"] = probe()
        raise Killed()

    def die_sync(*_a, **_k):
        at_kill["row"] = probe()
        raise Killed()
    if kind == "manual_mass_send":
        return patch.object(mq, "_close_mass_run", die_async)
    if kind == "vault_send":
        return patch.object(relay_host, "record_fan_send", die_async)
    return patch.object(send_ops.Claim, "done", lambda self, result: die_sync())


async def kill(kind: str, point: str) -> list[Check]:
    target, anchor = _target(kind), f"kill-{point}"
    at_kill: dict = {}

    def probe():
        r = rows(kind, target, anchor if kind != "vault_send" else None)
        return r[0] if r else None

    def die_before(fake, url, body):
        at_kill["row"] = probe()
        raise Killed()

    def die_after_accept(fake, url, body):
        _step(kind)(fake, url, body)
        at_kill["row"] = probe()
        raise Killed()

    http = FakeHttp({"after_claim": die_before, "accepted": die_after_accept, "after_wire": _step(kind)}[point])
    killed = False
    with _after_wire_patch(kind, at_kill, probe) if point == "after_wire" else contextlib.nullcontext():
        try:
            await send(kind, http, target, anchor)
        except Killed:
            killed = True
    want_at_kill = "sent" if (point, kind) == ("after_wire", "vault_send") else "claimed"
    out: list[Check] = [(f"{kind} kill {point}: kill point reached (claim row {want_at_kill})",
                         killed and (at_kill.get("row") or {}).get("state") == want_at_kill,
                         {"killed": killed, "row": at_kill.get("row"), "calls": http.calls})]
    restart()
    after = probe()
    again = FakeHttp(_step(kind))
    if kind == "vault_send":
        import vault_upload
        await asyncio.to_thread(vault_upload.sweep, lambda aid: _vault_client(again))
        ok = not wire_calls(again) and (after or {}).get("state") == want_at_kill.replace("claimed", "uncertain")
        want = "the sweep never resends"
        answer = None
    else:
        st, body = await send(kind, again, target, anchor)
        answer = [st, body]
        ok = (after or {}).get("state") == "uncertain" and (st, err(body)) == (409, "op_uncertain") \
            and not wire_calls(again)
        want = "open claim is uncertain, never resent"
    accepts = len(http.accepts) + len(again.accepts)
    out.append((f"{kind} kill {point}: after restart {want}; ≤1 accept for the op", ok and accepts <= 1,
                {"row_after_restart": after, "resubmit": answer, "accepts": accepts, "resubmit_calls": again.calls}))
    return out


async def env_unset() -> list[Check]:
    out: list[Check] = []
    with cells(on=False):
        for kind in KINDS:
            target = _target(kind)
            plain, tagged = FakeHttp(_step(kind)), FakeHttp(_step(kind))
            s1, _ = await send(kind, plain, target, None)
            if kind == "publish_now":
                target = next(_sids)
            s2, _ = await send(kind, tagged, target if kind != "vault_send" else next(_fans), "op-env", part=1)
            same = [c[0] for c in wire_calls(plain)] == [c[0] for c in wire_calls(tagged)] and len(wire_calls(plain)) == 1
            out.append((f"env unset: {kind} with/without X-Op-Id = one wire call, as main", s1 == s2 == 200 and same,
                        {"answers": [s1, s2], "plain": plain.calls, "tagged": tagged.calls}))
    out.append(("env unset: no send_ops rows for the manual kinds", not any(rows(k, 0) for k in KINDS)
                and not _has_rows(), {}))
    return out


def _has_rows() -> bool:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        try:
            return c.execute("SELECT 1 FROM send_ops WHERE kind IN (%s)" % ",".join("?" * len(KINDS)),
                             KINDS).fetchone() is not None
        except sqlite3.OperationalError:
            return False


async def run_all() -> list[Check]:
    from _send_kill_cell import _seed
    await _seed()
    checks = await env_unset()
    restart()
    with cells():
        for kind in KINDS:
            checks += await clean(kind)
        checks += await mass_side_effects()
        checks += await mass_gifs()
        for kind in ("manual_mass_send", "native_schedule", "publish_now"):
            checks += await refused_resubmit(kind)
        checks += await pre_wire_refusal()
        checks += await unclaimed()
        checks += await post_now()
        checks += await vault_retry_replays()
        for kind in KINDS:
            for point in ("after_claim", "accepted", "after_wire"):
                checks += await kill(kind, point)
    return checks


def _mutant(name: str):
    import send_ops
    from _send_kill_cell import _mutant as cell_mutant, _patches
    if name == "one_part":
        return _patches((send_ops, "part", lambda headers: 0))
    return cell_mutant(name)


MUTANTS = {
    "tripwire_bypass": tuple(f"{k}: no X-Op-Id in Cell mode → unclaimed_send, 0 wire calls"
                             for k in ("manual_mass_send", "manual_mass_schedule", "native_schedule")),
    "claim_after_wire": tuple(f"{k} kill after_claim: kill point reached (claim row claimed)" for k in KINDS),
    "one_part": ("manual mass + 2 extra GIFs: 3 parts, each accepted once",),
}


def run_mutant(name: str) -> int:
    from _send_kill_cell import report
    if name not in MUTANTS:
        print(f"--break manual:{name}: no such mutant (have {', '.join(MUTANTS)})")
        return 2

    async def go():
        with _mutant(name):
            return await run_all()
    checks = asyncio.run(go())
    failed = report(checks)
    own = MUTANTS[name]
    if absent := [c for c in own if c not in {n for n, _, _ in checks}]:
        print(f"--break manual:{name}: own checks never ran: {absent}")
        return 1
    green = [c for c in own if c not in failed]
    print(f"--break manual:{name}: {len(own) - len(green)}/{len(own)} own checks red"
          + (f"; still green: {green}" if green else ""))
    return 0 if not green else 1
