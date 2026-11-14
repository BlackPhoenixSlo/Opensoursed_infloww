#!/usr/bin/env python3
"""Ultra plans end to end (ultra step 4; docs/plans/ultra-mode/issues/06, 13, 05): MCP propose_plan / plan_status,
the owner's routes (/admin/ultra/plans/*), the executor (ultra_run) and the send tools, through the real app
in-process (httpx ASGITransport) on the two-Agency bench with a fake OnlyFans client.

Cases:
  case_propose_stores_post_chain — propose_plan over MCP: plan_id, the post-chain steps (OF-restricted word
                                   doubled), open_url = base + /ultra/plans/{id}; the owner's GET shows the card
                                   with the FULL text; plan_status answers awaiting_ok.
  case_propose_refusals          — the chain refuses a send's text (step + stage named), a bad tool / bad args /
                                   forward reference / a reference in a send / another Agency's Creator refuse
                                   the plan; a chained text that reads like a reference (emoji strip turns
                                   "😘$pick.id" into "$pick.id") is refused by the second validation; nothing stored.
  case_ok_guards                 — wrong sha256 → 409, malformed → 422; a bearer on /ok (alone or beside the
                                   owner's cookie) → 403 (and no run); a chatter → 403; signed out → 401; Agency B on A's plan → 404 (GET, OK, cancel);
                                   plan_status with B's token → error 404.
  case_bearer_raw_send_routes    — a bearer's raw POST to the mass / post routes → 403, OnlyFans never called.
  case_happy_path                — read → write with a `$pick...` reference → send with literal ids: each step done
                                   in order; the folder gets the referenced media id; the send carries its literal
                                   media id and the post-chain text byte-for-byte;
                                   the mass's OnlyFans id kept on its step; step open_urls (no separate report, in view or plan_status); one ultra_done notification linking the plan; audit: one
                                   row per inner write/send naming Creator A, none for /admin/ultra/plans*; a
                                   second OK → 409 (no second run).
  case_double_ok_race            — two OKs at once (asyncio.gather): one 200, one 409, one executor run (one post).
  case_send_gate                 — toolbox.call of a send with a made-up plan_step, a pending step, an awaiting plan or
                                   args other than the started step's → 403, OnlyFans never called; the started
                                   step of a running plan with its exact args goes out.
  case_send_5xx_uncertain        — OF answers 500 (the mass route 502): the send is uncertain, its error one
                                   sentence ("OnlyFans answered 500: …"), the plan failed, later steps skipped,
                                   OnlyFans called exactly once (no retry).
  case_send_fans_skipped         — the mass route drops an approved fan id (opt-out list): the step is done with a
                                   plain note "sent to 1 of 2 fans by id: 1 skipped …" (view + plan_status); every
                                   id dropped → the route refuses (no OF call), the step failed, the next skipped.
  case_send_timeout_uncertain    — a post past STEP_TIMEOUT_S: uncertain, the next step skipped, never re-sent.
  case_cancel_between_steps      — cancel while step 1 runs: step 1 finishes, step 2 is skipped, plan cancelled;
                                   cancelling an awaiting plan → cancelled at once, its steps skipped, its OK → 409.
  case_cancel_stale_read         — cancel read `awaiting_ok` but an OK flipped it first: the run is flagged (its
                                   next step skipped); already cancelled → 409, never a silent 200.
  case_end_save_fails            — the executor's final save raises: it still leaves _TASKS / _CANCEL; the row
                                   stays `running` until a cancel (no executor here) marks it interrupted; no
                                   ultra_done notification.
  case_row_ended_elsewhere_stops_run — the row leaves running mid-step: the next save misses, the run stops
                                   (no step 2 call), the row is never written back to running; no notification.
  case_expiry_never_over_running — a stale expiry read never turns a running row expired.
  case_start_save_fails          — the `started` save raises: the step was never called → skipped, not uncertain.
  case_executor_crash            — the executor raises mid-step: the plan ends failed, the started step uncertain,
                                   the later step skipped (never left pending).
  case_executor_cancelled        — the executor task is cancelled mid-step: the plan is interrupted (never done),
                                   the started step uncertain, the later step skipped; the cancellation re-raised.
  case_restart_recovery          — a `running` row at relay start → interrupted, started → uncertain, pending →
                                   skipped (ultra_run.recover, the startup hook's call).
  case_expiry                    — an awaiting plan past 10 min reads `expired`; its OK → 409.

Seeded straight into the temp DB; no network, no real OnlyFans.

Run: ./venv/bin/python service/tests/test_ultra_plans.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import mcp_api  # noqa: E402
import server  # noqa: E402
import toolbox  # noqa: E402
import ultra_decide as ud  # noqa: E402
import ultra_run  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, Action, AgencyNotification, UltraPlan, VaultItem  # noqa: E402

IDS = fx.seed_two_agencies()
CA, CB = IDS["creator_a"], IDS["creator_b"]
OWNER_A = IDS["agency_a_owner"]
A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")
CHAT = fx.login_chatter("chatter_a")
ANON = _harness.make_client()
PHOTO = 9301


HA = {"Authorization": f"Bearer {fx.mint_token(A)}"}
HB = {"Authorization": f"Bearer {fx.mint_token(B)}"}
COOKIE_A = {"Cookie": "; ".join(f"{k}={v}" for k, v in A.cookies.items())}
FWD = {"X-Forwarded-Host": "app.example.com", "X-Forwarded-Proto": "https"}


class _FakeOF:
    """server._get_client (mass + post routes) and ax._make_client (folder routes): every call recorded."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.mass_error: int | None = None
        self.post_sleep = 0.0

    def reset(self) -> None:
        self.calls.clear()
        self.mass_error, self.post_sleep = None, 0.0

    def send_mass_message(self, **kw):
        self.calls.append(("mass", kw))
        if self.mass_error:
            # server._proxy's answer to an OF error: 502 with OF's status + body
            raise HTTPException(502, {"upstream_status": self.mass_error, "upstream_body": '{"error":"fake OF 500"}'})
        return {"id": 4242, "text": kw.get("text")}

    def create_post(self, **kw):
        self.calls.append(("post", kw))
        time.sleep(self.post_sleep)
        return {"id": 5151}

    def create_vault_list(self, name):
        self.calls.append(("folder", name))
        return {"id": 7001, "name": name}

    def add_media_to_vault_list(self, list_id, media_ids):
        self.calls.append(("folder_add", int(list_id), list(media_ids)))
        return {"success": True}


OF = _FakeOF()
server._get_client = lambda *_a, **_k: OF  # type: ignore[assignment]
account_registry.upsert_account(CA, nickname="Ava")  # the OF routes resolve the Creator through the registry
ax._make_client = lambda *_a, **_k: OF  # type: ignore[assignment]


async def _seed() -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(VaultItem(account_id=CA, media_id=PHOTO, kind="photo", raw_json=json.dumps({"id": PHOTO}),
                        created_at=now, updated_at=now, last_seen_run_id=1, search_text="halloween costume",
                        tags="[]", of_folder_ids="[]"))
asyncio.run(_seed())

_ids = itertools.count(1)
_TEXT = "one drink for halloween, new set inside"  # "drink" is OF-restricted → "driink"
_CHAINED = "one driink for halloween, new set inside"


_PICK = {"id": "pick", "tool": "vault_search", "args": {"account_id": CA, "query": "halloween"}}


def _mass(sid="mass", **kw):
    return {"id": sid, "tool": "mass_send",
            "args": {"account_id": CA, "text": _TEXT, "user_lists": ["fans"], **kw}}


def _post(sid="post", **kw):
    return {"id": sid, "tool": "post_create", "args": {"account_id": CA, "text": "new post tonight", **kw}}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver")


async def _tool(c, name, args, headers=HA) -> dict:
    msg = {"jsonrpc": "2.0", "id": next(_ids), "method": "tools/call", "params": {"name": name, "arguments": args}}
    r = await c.post(mcp_api.PATH, json=msg, headers=headers)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    return {"isError": res["isError"], **res["structuredContent"]}


async def _propose(c, *steps, summary="Halloween push") -> dict:
    out = await _tool(c, "propose_plan", {"summary": summary, "steps": list(steps)}, {**HA, **FWD})
    assert out["isError"] is False, out
    return out


async def _get(c, pid, headers=COOKIE_A) -> httpx.Response:
    return await c.get(f"/admin/ultra/plans/{pid}", headers=headers)


async def _ok(c, pid, sha, headers=COOKIE_A) -> httpx.Response:
    return await c.post(f"/admin/ultra/plans/{pid}/ok", json={"sha256": sha}, headers=headers)


async def _until_final(c, pid, timeout=10.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = (await _get(c, pid)).json()
        if v["status"] in ud.FINAL:
            return v
        await asyncio.sleep(0.05)
    raise AssertionError(f"plan {pid} never finished: {v}")


async def _last_action_id() -> int:
    async with get_session() as s:
        return (await s.execute(select(Action.id).order_by(Action.id.desc()).limit(1))).scalar() or 0


async def _actions(since: int) -> list[tuple]:
    async with get_session() as s:
        return [tuple(r) for r in (await s.execute(
            select(Action.action, Action.account_id).where(Action.id > since).order_by(Action.id))).all()]


async def _plan_count() -> int:
    async with get_session() as s:
        return len((await s.execute(select(UltraPlan.id))).all())


def _states(v) -> list[str]:
    return [s["state"] for s in v["step_states"]]


async def _done_notes(pid: str) -> int:
    async with get_session() as s:
        notes = (await s.execute(select(AgencyNotification).where(AgencyNotification.kind == "ultra_done"))).scalars()
        return sum(json.loads(n.data_json or "{}").get("href") == f"/ultra/plans/{pid}" for n in notes)


# ── cases ────────────────────────────────────────────────────────────

async def case_propose_stores_post_chain() -> None:
    async with _client() as c:
        out = await _propose(c, _mass(price=0))
        pid = out["plan_id"]
        assert out["status"] == "awaiting_ok" and out["open_url"] == f"https://app.example.com/ultra/plans/{pid}", out
        assert out["steps"][0]["args"]["text"] == _CHAINED, out["steps"]
        v = (await _get(c, pid)).json()
        assert out["expires_at"] == v["expires_at"] and out["steps"] == v["steps"], (out, v)
        assert out["open_url"] == "https://app.example.com" + ud.plan_path(pid)
        assert v["source"] == "mcp" and v["sha256"] == ud.digest({"summary": "Halloween push", "steps": v["steps"]})
        card = v["card"][0]
        assert card["effect"] == "send" and card["text"] == _CHAINED, card
        assert dict(map(tuple, card["rows"]))["Audience"] == "lists fans", card
        st = await _tool(c, "plan_status", {"plan_id": pid})
        assert st["status"] == "awaiting_ok" and st["open_url"].endswith(f"/ultra/plans/{pid}"), st
        assert f"the OK expires after {ud.OK_TTL_TEXT}." in mcp_api.PROPOSE_DESCRIPTION


async def case_propose_refusals() -> None:
    async with _client() as c:
        before = await _plan_count()
        table = [
            ([_mass(text="add me on telegram")], ("mass", "text", "stage offplatform")),
            ([_mass(text="*smiles* new set")], ("mass", "text", "stage narration")),
            ([{"id": "x", "tool": "fan_dm", "args": {}}], ("x", "tool", "unknown tool")),
            ([_mass(price="free")], ("mass", "price", "")),
            ([_mass(media_files=[PHOTO], price=99999)], ("mass", "price", "between $3 and $200")),
            ([_mass(media_files=[PHOTO], price=1)], ("mass", "price", "between $3 and $200")),
            ([{"id": "folder", "tool": "of_folder_create",
               "args": {"account_id": CA, "name": "x", "media_ids": ["$later.id"]}}, _post("later")],
             ("folder", "media_ids.0", "does not run before")),
            ([_mass(account_id=CB)], ("mass", "account_id", "not one of your Creators")),
            ([_PICK, _mass(media_files=["$pick.data_only.list.0.id"])], ("mass", "media_files.0", "literal")),
            ([_PICK, _mass(user_ids=["$pick.data_only.list.0.id"])], ("mass", "user_ids.0", "literal")),
        ]
        for steps, (step, field, words) in table:
            out = await _tool(c, "propose_plan", {"summary": "x", "steps": steps})
            assert out["isError"] is True and out["error"]["status"] == 422, out
            errs = out["error"]["detail"]["errors"]
            assert any(e["step"] == step and e["field"] == field and words in e["error"] for e in errs), (steps, errs)
        async with get_session() as s:
            s.add(AccountAiConfig(account_id=CA, style_config_json=json.dumps({"strip_emojis": True})))
        try:
            out = await _tool(c, "propose_plan", {"summary": "x", "steps": [_PICK, _mass(text="😘$pick.id")]})
        finally:
            async with get_session() as s:
                await s.execute(delete(AccountAiConfig).where(AccountAiConfig.account_id == CA))
        errs = out["error"]["detail"]["errors"]
        assert out["isError"] is True and errs == [{"step": "mass", "field": "text", "error": ud.SEND_LITERAL}], out
        assert await _plan_count() == before


def case_ok_guards() -> None:
    # Sync TestClients: each request gets its own context, as on the real server. (An in-task AsyncClient leaks
    # the session ContextVars of one request into the next, which would make a chatter look like owner A.)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "propose_plan", "arguments": {"summary": "guards", "steps": [_mass()]}}}
    pid = ANON.post(mcp_api.PATH, json=msg, headers=HA).json()["result"]["structuredContent"]["plan_id"]
    sha = A.get(f"/admin/ultra/plans/{pid}").json()["sha256"]
    ok = lambda client, sha=sha, headers=None: client.post(  # noqa: E731
        f"/admin/ultra/plans/{pid}/ok", json={"sha256": sha}, headers=headers or {})
    assert ok(A, "0" * 64).status_code == 409
    assert ok(A, "zz").status_code == 422
    r = ok(ANON, headers=HA)
    assert r.status_code == 403 and "access token" in r.text, r.text
    r = ok(A, headers=HA)  # a bearer beside the owner's cookie: the cookie is stripped, still refused
    assert r.status_code == 403, r.text
    r = ok(CHAT)
    assert r.status_code == 403 and "chatter" in r.text, r.text
    assert ok(ANON).status_code == 401
    assert B.get(f"/admin/ultra/plans/{pid}").status_code == 404
    assert ok(B).status_code == 404
    assert B.post(f"/admin/ultra/plans/{pid}/cancel").status_code == 404
    st = {**msg, "params": {"name": "plan_status", "arguments": {"plan_id": pid}}}
    res = ANON.post(mcp_api.PATH, json=st, headers=HB).json()["result"]
    assert res["isError"] is True and res["structuredContent"]["error"]["status"] == 404, res
    assert A.get(f"/admin/ultra/plans/{pid}").json()["status"] == "awaiting_ok" and OF.calls == []


async def case_bearer_raw_send_routes() -> None:
    OF.reset()
    async with _client() as c:
        r = await c.post("/api/of/v2/messages/queue", params={"account_id": CA},
                         json={"text": "hi", "user_lists": ["fans"]}, headers={**HA, "X-Account-Id": CA})
        assert r.status_code == 403, r.text
        r = await c.post("/api/of/v2/posts", params={"account_id": CA}, json={"text": "hi"},
                         headers={**HA, "X-Account-Id": CA})
        assert r.status_code == 403, r.text
    assert OF.calls == [], OF.calls


async def case_happy_path() -> None:
    OF.reset()
    async with _client() as c:
        ref = "$pick.data_only.list.0.id"
        out = await _propose(
            c, _PICK,
            {"id": "folder", "tool": "of_folder_create", "args": {"account_id": CA, "name": "Halloween", "media_ids": [ref]}},
            _mass(media_files=[PHOTO], price=12))
        pid = out["plan_id"]
        sha = (await _get(c, pid)).json()["sha256"]
        since = await _last_action_id()
        r = await _ok(c, pid, sha)
        assert r.status_code == 200 and r.json()["status"] in ("running", "done"), r.text
        v = await _until_final(c, pid)
        assert v["status"] == "done" and _states(v) == ["done", "done", "done"], v
        kinds = [x[0] for x in OF.calls]
        assert kinds == ["folder", "folder_add", "mass"], OF.calls
        assert OF.calls[1][2] == [PHOTO], OF.calls
        mass = OF.calls[2][1]
        assert mass["text"] == _CHAINED and mass["media_files"] == [PHOTO] and mass["price"] == 12, mass
        assert "report" not in v and [s["open_url"] for s in v["step_states"]][1:] == [
            "/growth/vault-pro", "/growth/smart-messages"], v["step_states"]
        assert v["step_states"][2]["result"] == {"id": 4242} and "result" not in v["step_states"][0], v
        st = await _tool(c, "plan_status", {"plan_id": pid})
        assert "report" not in st and st["step_states"] == v["step_states"], st
        rows = await _actions(since)
        assert ("POST /admin/vault-ai/of-folders", CA) in rows, rows
        assert ("POST /api/of/v2/messages/queue", CA) in rows, rows
        assert len([a for a, _ in rows if a in ("POST /admin/vault-ai/of-folders", "POST /api/of/v2/messages/queue")]) == 2
        assert not any("/admin/ultra/plans" in a for a, _ in rows), rows
        async with get_session() as s:
            notes = (await s.execute(select(AgencyNotification).where(
                AgencyNotification.agency_user_id == OWNER_A, AgencyNotification.kind == "ultra_done"))).scalars().all()
        mine = [n for n in notes if json.loads(n.data_json or "{}").get("href") == f"/ultra/plans/{pid}"]
        assert len(mine) == 1 and mine[0].text.startswith("Ultra plan done: Halloween push (3 of 3"), [n.text for n in notes]
        assert (await _ok(c, pid, sha)).status_code == 409
        assert len(OF.calls) == 3


async def case_double_ok_race() -> None:
    OF.reset()
    OF.post_sleep = 0.2
    async with _client() as c:
        pid = (await _propose(c, _post()))["plan_id"]
        sha = (await _get(c, pid)).json()["sha256"]
        runs, real = [], ultra_run._run

        async def counted(*a, **k):
            runs.append(a[0])
            await real(*a, **k)
        ultra_run._run = counted
        try:
            codes = sorted(r.status_code for r in await asyncio.gather(_ok(c, pid, sha), _ok(c, pid, sha)))
            v = await _until_final(c, pid)
        finally:
            ultra_run._run = real
    assert codes == [200, 409], codes
    assert runs == [pid] and v["status"] == "done" and [k for k, _ in OF.calls] == ["post"], (runs, v, OF.calls)


async def case_send_gate() -> None:
    OF.reset()
    tool, creds = ud.TOOLS["mass_send"], toolbox.Creds(cookie=COOKIE_A["Cookie"])
    args = {"account_id": CA, "text": "hi there", "user_lists": ["fans"]}
    plan = {"summary": "gate", "steps": [{"id": "mass", "tool": "mass_send", "args": args}]}
    pid = "e" * 32

    async def put(status, state):
        async with get_session() as s:
            await s.execute(delete(UltraPlan).where(UltraPlan.id == pid))
            s.add(UltraPlan(id=pid, owner_user_id=OWNER_A, source="mcp", plan_json=json.dumps(plan),
                            plan_sha256=ud.digest(plan), status=status,
                            step_states=json.dumps([{"id": "mass", "state": state}])))
    try:
        for step, status, state, a in [("x", "running", "started", args), (f"{pid}:mass", "running", "pending", args),
                                       (f"{pid}:mass", "awaiting_ok", "pending", args),
                                       (f"{pid}:mass", "running", "started", {**args, "text": "other"}),
                                       (f"{pid}:other", "running", "started", args)]:
            await put(status, state)
            r = await toolbox.call(tool, a, creds, plan_step=step)
            assert r["error"] == {"status": 403, "detail": toolbox.SEND_REFUSED}, (step, status, state, r)
        assert OF.calls == [], OF.calls
        await put("running", "started")
        r = await toolbox.call(tool, args, creds, plan_step=f"{pid}:mass")
        assert "error" not in r and r["id"] == 4242, r
        assert [k for k, _ in OF.calls] == ["mass"], OF.calls
    finally:
        async with get_session() as s:
            await s.execute(delete(UltraPlan).where(UltraPlan.id == pid))


async def case_send_5xx_uncertain() -> None:
    OF.reset()
    OF.mass_error = 500
    async with _client() as c:
        out = await _propose(c, _mass(), _post())
        pid = out["plan_id"]
        assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
        v = await _until_final(c, pid)
    assert v["status"] == "failed" and _states(v) == ["uncertain", "skipped"], v
    assert v["step_states"][0]["error"] == "OnlyFans answered 500: fake OF 500", v  # one sentence, never a dict
    assert [k for k, _ in OF.calls] == ["mass"], OF.calls  # once: no retry, the post never ran


async def case_send_fans_skipped() -> None:
    import audiences
    real = audiences.exclude_list_fan_ids

    async def opted_out(_aid, _name):
        return {222}
    audiences.exclude_list_fan_ids = opted_out
    try:
        OF.reset()
        async with _client() as c:
            pid = (await _propose(c, _mass(user_lists=[], user_ids=[111, 222])))["plan_id"]
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            v = await _until_final(c, pid)
            st = await _tool(c, "plan_status", {"plan_id": pid})
        assert v["status"] == "done" and _states(v) == ["done"], v
        assert [kw["included_users"] for k, kw in OF.calls] == [[111]], OF.calls
        note = "sent to 1 of 2 fans by id: 1 skipped (opted out or already queued)"
        assert v["step_states"][0]["note"] == note and st["step_states"][0]["note"] == note, (v, st)
        OF.reset()  # nobody left: the route sends nothing (no OF call) and the step is not done
        async with _client() as c:
            pid = (await _propose(c, _mass(user_lists=[], user_ids=[222]), _post()))["plan_id"]
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            v = await _until_final(c, pid)
        assert v["status"] == "failed" and _states(v) == ["failed", "skipped"], v
        assert v["step_states"][0]["error"].startswith("nobody left to send to: 1 of 1 fan"), v
        assert OF.calls == [], OF.calls
    finally:
        audiences.exclude_list_fan_ids = real


async def case_send_timeout_uncertain() -> None:
    OF.reset()
    OF.post_sleep = 1.0
    saved, ultra_run.STEP_TIMEOUT_S = ultra_run.STEP_TIMEOUT_S, 0.3
    try:
        async with _client() as c:
            out = await _propose(c, _post(), _mass())
            pid = out["plan_id"]
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            v = await _until_final(c, pid)
            await asyncio.sleep(1.0)  # the shielded post finishes on its own; nothing re-sends it
    finally:
        ultra_run.STEP_TIMEOUT_S = saved
    assert v["status"] == "failed" and _states(v) == ["uncertain", "skipped"], v
    assert [k for k, _ in OF.calls] == ["post"], OF.calls


async def case_cancel_between_steps() -> None:
    OF.reset()
    OF.post_sleep = 0.5
    async with _client() as c:
        out = await _propose(c, _post(), _mass())
        pid = out["plan_id"]
        assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
        await asyncio.sleep(0.1)
        r = await c.post(f"/admin/ultra/plans/{pid}/cancel", headers=COOKIE_A)
        assert r.status_code == 200, r.text
        v = await _until_final(c, pid)
        assert v["status"] == "cancelled" and _states(v) == ["done", "skipped"], v
        assert [k for k, _ in OF.calls] == ["post"], OF.calls
        out = await _propose(c, _mass())
        pid2 = out["plan_id"]
        sha2 = (await _get(c, pid2)).json()["sha256"]
        r = await c.post(f"/admin/ultra/plans/{pid2}/cancel", headers=COOKIE_A)
        assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
        assert _states(r.json()) == ["skipped"], r.json()  # closed in the same flip: never left "pending"
        assert (await _ok(c, pid2, sha2)).status_code == 409


def _stale_row_once():
    """ultra_run._row whose first read says `awaiting_ok` (a read that raced an OK / a cancel)."""
    real, first = ultra_run._row, [True]

    async def stale(pid, uid):
        row = await real(pid, uid)
        if first[0] and row is not None:
            first[0], row.status = False, "awaiting_ok"
        return row
    return real, stale


async def case_cancel_stale_read() -> None:
    OF.reset()
    OF.post_sleep = 0.5
    async with _client() as c:
        pid = (await _propose(c, _post(), _mass()))["plan_id"]
        assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
        await asyncio.sleep(0.1)
        real, ultra_run._row = _stale_row_once()
        try:
            await ultra_run.cancel(pid, OWNER_A)
        finally:
            ultra_run._row = real
        v = await _until_final(c, pid)
        assert v["status"] == "cancelled" and _states(v) == ["done", "skipped"], v
        assert [k for k, _ in OF.calls] == ["post"], OF.calls
        pid2 = (await _propose(c, _mass()))["plan_id"]
        assert (await c.post(f"/admin/ultra/plans/{pid2}/cancel", headers=COOKIE_A)).status_code == 200
        real, ultra_run._row = _stale_row_once()
        try:
            await ultra_run.cancel(pid2, OWNER_A)
            raise AssertionError("a cancel of a cancelled plan must refuse")
        except ultra_run.Refused as e:
            assert e.status == 409 and "cancelled" in e.detail, e.detail
        finally:
            ultra_run._row = real


async def case_end_save_fails() -> None:
    OF.reset()
    real = ultra_run._save

    async def save(pid, states, status="running"):
        if status in ud.FINAL:
            raise RuntimeError("db went away")
        await real(pid, states, status)
    async with _client() as c:
        pid = (await _propose(c, _post()))["plan_id"]
        ultra_run._save = save
        try:
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            for _ in range(200):
                if pid not in ultra_run._TASKS:
                    break
                await asyncio.sleep(0.05)
        finally:
            ultra_run._save = real
        assert pid not in ultra_run._TASKS and pid not in ultra_run._CANCEL
        v = (await _get(c, pid)).json()
        assert v["status"] == "running" and _states(v) == ["started"], v
        assert await _done_notes(pid) == 0, "no 'done' notification for an end that was never saved (m7)"
        r = await c.post(f"/admin/ultra/plans/{pid}/cancel", headers=COOKIE_A)
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["status"] == "interrupted" and _states(v) == ["uncertain"] and v["finished_at"], v
        assert (await c.post(f"/admin/ultra/plans/{pid}/cancel", headers=COOKIE_A)).status_code == 409
        assert pid not in ultra_run._CANCEL


async def case_row_ended_elsewhere_stops_run() -> None:
    """m1: the row leaves running while step 1 runs (ended elsewhere): the next per-step save misses, the run
    stops before step 2's call and never writes the row back to running; no notification."""
    OF.reset()
    OF.post_sleep = 0.5
    async with _client() as c:
        pid = (await _propose(c, _post(), _mass()))["plan_id"]
        assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
        await asyncio.sleep(0.1)
        async with get_session() as s:
            await s.execute(update(UltraPlan).where(UltraPlan.id == pid).values(status="interrupted"))
        for _ in range(200):
            if pid not in ultra_run._TASKS:
                break
            await asyncio.sleep(0.05)
        v = (await _get(c, pid)).json()
    assert v["status"] == "interrupted" and [k for k, _ in OF.calls] == ["post"], (v, OF.calls)
    assert await _done_notes(pid) == 0


async def case_expiry_never_over_running() -> None:
    """m1: a read that judged a plan expired while an OK flipped it to running writes nothing: it stays running."""
    plan = {"summary": "raced", "steps": [_post("a")]}
    async with get_session() as s:
        s.add(UltraPlan(id="e" * 32, owner_user_id=OWNER_A, source="mcp", plan_json=json.dumps(plan),
                        plan_sha256=ud.digest(plan), status="running", created_at=datetime.utcnow() - timedelta(minutes=11),
                        step_states=json.dumps([{"id": "a", "state": "started"}])))
    real, ud.expired = ud.expired, lambda *_a: True  # the stale read: it saw awaiting_ok
    try:
        row = await ultra_run._row("e" * 32, OWNER_A)
    finally:
        ud.expired = real
    assert row.status == "running" and row.finished_at is None, row.status
    async with get_session() as s:
        assert (await s.get(UltraPlan, "e" * 32)).status == "running"


async def case_start_save_fails() -> None:
    """m5: the save of a step's `started` raises: that step was never called, so it ends skipped (not uncertain)."""
    OF.reset()
    real = ultra_run._save

    async def save(pid, states, status="running"):
        if status == "running":
            raise RuntimeError("db went away")
        await real(pid, states, status)
    async with _client() as c:
        pid = (await _propose(c, _post(), _mass()))["plan_id"]
        ultra_run._save = save
        try:
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            v = await _until_final(c, pid)
        finally:
            ultra_run._save = real
    assert v["status"] == "failed" and _states(v) == ["skipped", "skipped"] and OF.calls == [], v


async def case_executor_crash() -> None:
    OF.reset()
    real = ultra_run._step

    async def boom(*_a, **_k):
        raise RuntimeError("executor bug")
    async with _client() as c:
        pid = (await _propose(c, _post(), _mass()))["plan_id"]
        ultra_run._step = boom
        try:
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            v = await _until_final(c, pid)
        finally:
            ultra_run._step = real
    assert v["status"] == "failed" and _states(v) == ["uncertain", "skipped"], v
    assert OF.calls == [] and pid not in ultra_run._TASKS


async def case_executor_cancelled() -> None:
    OF.reset()
    real, entered = ultra_run._step, asyncio.Event()

    async def hang(*_a, **_k):
        entered.set()
        await asyncio.sleep(30)
    async with _client() as c:
        pid = (await _propose(c, _post(), _mass()))["plan_id"]
        ultra_run._step = hang
        try:
            assert (await _ok(c, pid, (await _get(c, pid)).json()["sha256"])).status_code == 200
            await asyncio.wait_for(entered.wait(), 5)
            task = ultra_run._TASKS[pid]
            task.cancel()
            try:
                await task
                raise AssertionError("the executor must re-raise its cancellation")
            except asyncio.CancelledError:
                pass
        finally:
            ultra_run._step = real
        v = (await _get(c, pid)).json()
    assert v["status"] == "interrupted" and _states(v) == ["uncertain", "skipped"] and v["finished_at"], v
    assert pid not in ultra_run._TASKS and OF.calls == []


async def case_restart_recovery() -> None:
    plan = {"summary": "left running", "steps": [_post("a"), _mass("b"), _post("c")]}
    states = [{"id": "a", "state": "done"}, {"id": "b", "state": "started"}, {"id": "c", "state": "pending"}]
    async with get_session() as s:
        s.add(UltraPlan(id="f" * 32, owner_user_id=OWNER_A, source="mcp", plan_json=json.dumps(plan),
                        plan_sha256=ud.digest(plan), status="running", step_states=json.dumps(states)))
    assert await ultra_run.recover() >= 1
    async with _client() as c:
        v = (await _get(c, "f" * 32)).json()
    assert v["status"] == "interrupted" and _states(v) == ["done", "uncertain", "skipped"], v
    assert await ultra_run.recover() == 0


async def case_expiry() -> None:
    async with _client() as c:
        out = await _propose(c, _mass())
        pid = out["plan_id"]
        sha = (await _get(c, pid)).json()["sha256"]
        async with get_session() as s:
            await s.execute(update(UltraPlan).where(UltraPlan.id == pid)
                            .values(created_at=datetime.utcnow() - timedelta(minutes=11)))
        assert (await _get(c, pid)).json()["status"] == "expired"
        r = await _ok(c, pid, sha)
        assert r.status_code == 409 and "expired" in r.text, r.text


if __name__ == "__main__":
    _harness.run()
