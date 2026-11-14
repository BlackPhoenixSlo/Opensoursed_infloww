#!/usr/bin/env python3
"""The pasted-logins queue (ultra-mode ticket 11; service/login_queue.py, remote_login_api.py queue routes),
through the real app in-process (httpx ASGITransport, so the worker task lives on the test's loop) on the
two-Agency bench. `remote_login.start_login` is FAKED: no Browserbase, no OnlyFans, no network; the test
drives each fake job's state.

Cases:
  case_happy_sequential  — a paste with a bad line: 200, the bad line by number only, entries waiting; one job
                           at a time in paste order (the second starts only after the first ends), each a
                           browserbase job for the owner on the relay's default proxy (none without a pool);
                           the started entry's password cleared at once; queue done, every password cleared.
  case_default_proxy_pool — the relay has an Inflowwww pool: the queue's jobs run on it.
  case_otp_surfaced      — a job asking for its 2FA code shows "otp" + its job id on GET; the owner's code to
                           /admin/login/remote/{job_id}/otp is taken (the job's principal is the owner); Agency
                           B's → 403.
  case_error_notice_moves_on — a failed job and a start that raises (message scrubbed of the password): an
                           `ultra_needs_you` notice "<email> not logged in" each (no "after 5 min": they
                           failed at once; linking the queue), and the queue moves on to the next entry; a job
                           whose own window ran out (remote_login.TIMED_OUT) files "... after 5 min".
  case_timeout           — a job that never ends within its window + GRACE_S: cancelled, given SETTLE_S to end,
                           still running → the entry an error, one notice, the queue moves on.
  case_timeout_then_done — a timed-out job that logs in while it winds down: the entry done, no notice, the
                           next login only after it ended.
  case_cancel            — cancel mid-run: queue cancelled, waiting entries cancelled, every password cleared,
                           the running job cancelled, no further start, no notice.
  case_busy_and_404      — a second paste while one runs → 409; after it ends a new one is taken; an unknown
                           queue id / another Agency's → 404 (GET and cancel), neutral wording; GET with no id
                           → the owner's last queue (404 with none, never another Agency's).
  case_cancelled_replaceable — a cancelled queue whose job still winds down: a new paste is taken at once; its
                           first login waits for that job to end.
  case_replaced_same_email — the same email re-pasted after Stop: started (with the new password) only once
                           the old job ended, never refused by the old job's email lock.
  case_replaced_still_running — the old job not ended within SETTLE_S: that email's entry an error
                           (STILL_ENDING) + notice, never started; another email runs.
  case_comma_email_bad_line — "email,secretA:secretB" is a bad line by number: the fragment reaches no
                           response, status, notice.
  case_body_gates        — no text / not a string / no login line → 400 (the bad lines by number, never their
                           text; the password never echoed); over MAX_PASTE → 413; playwright missing → 501;
                           Browserbase env missing → 503; no queue started by any of them.
  case_principal_gates   — every queue route: a chatter → 403, a bearer (alone or beside the owner's cookie) → 403, signed out →
                           401: a bearer never reaches the login queue; /admin/login is audit-skipped and
                           chatter-blocked.
  case_secrets_nowhere   — after a full run: no password in any response, log line (any logger, DEBUG), audit
                           row or notification.

Run: ./venv/bin/python service/tests/test_login_queue.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import importlib.machinery  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import uuid  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import chatters  # noqa: E402
import employees  # noqa: E402
import login_paste  # noqa: E402
import login_queue as lq  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import remote_login as rl  # noqa: E402
import remote_login_api  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action, AgencyNotification  # noqa: E402

IDS = fx.seed_two_agencies()
OWNER_A, OWNER_B = IDS["agency_a_owner"], IDS["agency_b_owner"]
A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")
CHAT = fx.login_chatter("chatter_a")
ANON = _harness.make_client()
HA = {"Authorization": f"Bearer {fx.mint_token(A)}"}
COOKIE_A = {"Cookie": "; ".join(f"{k}={v}" for k, v in A.cookies.items())}
COOKIE_B = {"Cookie": "; ".join(f"{k}={v}" for k, v in B.cookies.items())}
Q = "/admin/login/remote/queue"
SECRETS = ["pwA-secret1", "pwB-secret2", "pwC-secret3"]
PASTE = f"a@x.com:{SECRETS[0]}\nnot a login {SECRETS[2]}\nb@x.com|{SECRETS[1]}"

lq.POLL_S = 0.01
os.environ["BROWSERBASE_API_KEY"], os.environ["BROWSERBASE_PROJECT_ID"] = "bb_test_key", "proj-xyz"
_pw = types.ModuleType("playwright")
_pw.__spec__ = importlib.machinery.ModuleSpec("playwright", None)  # the route's find_spec sees it installed
sys.modules["playwright"] = _pw


class _FakeStart:
    """remote_login.start_login stand-in: each call a registered job the test drives; `raise_for` emails raise
    an error carrying the password (the queue must scrub it)."""

    def __init__(self):
        self.calls: list[dict] = []
        self.jobs: list[rl.RemoteLoginJob] = []
        self.raise_for: set[str] = set()

    def reset(self) -> None:
        self.calls, self.jobs, self.raise_for = [], [], set()
        rl._jobs.clear()
        lq._QUEUES.clear()

    def __call__(self, **kw):
        self.calls.append(dict(kw))
        if kw["email"] in self.raise_for:
            raise rl.RemoteLoginConflict(f"busy for {kw['email']} ({kw['password']})")
        now = time.time()
        job = rl.RemoteLoginJob(id=uuid.uuid4().hex, email=kw["email"], principal=kw["principal"],
                                created_at=now, expires_at=now + rl.JOB_WINDOW_S, proxy=kw["proxy"],
                                backend=kw["backend"])
        job.live_view_url = "https://bb.example/live/1"
        rl._jobs[job.id] = job
        self.jobs.append(job)
        return job


START = _FakeStart()
rl.start_login = START  # type: ignore[assignment]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver")


async def _until(cond, timeout=5.0) -> None:
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("condition never met")
        await asyncio.sleep(0.01)


async def _paste(c, text=PASTE, headers=COOKIE_A) -> dict:
    r = await c.post(Q, json={"text": text}, headers=headers)
    assert r.status_code == 200, r.text
    assert not any(s in r.text for s in SECRETS), r.text
    return r.json()


async def _get(c, qid, headers=COOKIE_A) -> dict:
    r = await c.get(f"{Q}/{qid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _queue(owner=OWNER_A) -> lq.Queue:
    return lq._QUEUES[owner]


async def _notes(owner=OWNER_A) -> list[AgencyNotification]:
    async with get_session() as s:
        return list((await s.execute(select(AgencyNotification).where(
            AgencyNotification.agency_user_id == owner, AgencyNotification.kind == "ultra_needs_you"))).scalars())


# ── cases ────────────────────────────────────────────────────────────

async def case_happy_sequential() -> None:
    START.reset()
    async with _client() as c:
        q = await _paste(c)
        assert q["state"] == "running" and q["bad_lines"] == [{"line": 2, "reason": login_paste.NOT_A_LOGIN}], q
        assert [e["email"] for e in q["entries"]] == ["a@x.com", "b@x.com"], q
        assert set(q["entries"][0]) == {"email", "state", "job_id", "message", "live_view_url", "account_id"}, q
        await _until(lambda: len(START.jobs) == 1)
        call = START.calls[0]
        assert (call["email"], call["password"], call["principal"], call["backend"], call["proxy"],
                call["proxy_defaulted"]) == ("a@x.com", SECRETS[0], OWNER_A, rl.BACKEND_BROWSERBASE,
                                             rl.PROXY_NONE, True), call
        assert _queue().entries[0].password is None and _queue().entries[1].password == SECRETS[1]
        await asyncio.sleep(0.05)
        assert len(START.jobs) == 1  # sequential: the second waits for the first
        v = await _get(c, q["id"])
        assert [e["state"] for e in v["entries"]] == [rl.STATE_STARTING, lq.WAITING], v
        assert v["entries"][0]["job_id"] == START.jobs[0].id and v["entries"][0]["live_view_url"], v
        START.jobs[0].account_id = "111"
        START.jobs[0].set_state(rl.STATE_DONE, "logged in")
        await _until(lambda: len(START.jobs) == 2)
        assert START.calls[1]["email"] == "b@x.com" and START.calls[1]["password"] == SECRETS[1]
        START.jobs[1].set_state(rl.STATE_DONE, "logged in")
        await _until(lambda: _queue().finished)
        v = await _get(c, q["id"])
    assert v["state"] == "done" and [e["state"] for e in v["entries"]] == [rl.STATE_DONE] * 2, v
    assert v["entries"][0]["account_id"] == "111" and v["entries"][0]["live_view_url"] is None, v
    assert all(e.password is None for e in _queue().entries)
    assert await _notes() == []


async def case_default_proxy_pool() -> None:
    START.reset()
    saved = proxy_registry.pool_entries
    proxy_registry.pool_entries = lambda *a, **k: [{"label": "pool-1"}]  # type: ignore[assignment]
    try:
        async with _client() as c:
            await _paste(c, "a@x.com:pw1")
            await _until(lambda: len(START.jobs) == 1)
            START.jobs[0].set_state(rl.STATE_DONE)
            await _until(lambda: _queue().finished)
    finally:
        proxy_registry.pool_entries = saved  # type: ignore[assignment]
    assert START.calls[0]["proxy"] == rl.PROXY_INFLOWWW, START.calls


async def case_otp_surfaced() -> None:
    START.reset()
    async with _client() as c:
        q = await _paste(c, "a@x.com:pw1")
        await _until(lambda: len(START.jobs) == 1)
        job = START.jobs[0]
        job.set_state(rl.STATE_OTP, "type the code")
        await _until(lambda: _queue().entries[0].state == rl.STATE_OTP)
        e = (await _get(c, q["id"]))["entries"][0]
        assert e["state"] == rl.STATE_OTP and e["job_id"] == job.id, e
        r = await c.post(f"/admin/login/remote/{job.id}/otp", json={"code": "123456"}, headers=COOKIE_B)
        assert r.status_code == 403, r.text
        r = await c.post(f"/admin/login/remote/{job.id}/otp", json={"code": "123456"}, headers=COOKIE_A)
        assert r.status_code == 200 and "123456" not in r.text, r.text
        assert job.take_otp() == "123456"
        job.set_state(rl.STATE_DONE)
        await _until(lambda: _queue().finished)


async def case_error_notice_moves_on() -> None:
    START.reset()
    START.raise_for = {"b@x.com"}
    async with _client() as c:
        q = await _paste(c, f"a@x.com:{SECRETS[0]}\nb@x.com:{SECRETS[1]}\nc@x.com:{SECRETS[2]}")
        await _until(lambda: len(START.jobs) == 1)
        START.jobs[0].fail("OnlyFans said the password is wrong")
        await _until(lambda: len(START.jobs) == 2)  # b's start raised; c started
        assert START.jobs[1].email == "c@x.com"
        START.jobs[1].set_state(rl.STATE_DONE)
        await _until(lambda: _queue().finished)
        v = await _get(c, q["id"])
    assert [e["state"] for e in v["entries"]] == [rl.STATE_ERROR, rl.STATE_ERROR, rl.STATE_DONE], v
    assert "busy for b@x.com" in v["entries"][1]["message"] and SECRETS[1] not in json.dumps(v), v
    notes = sorted(await _notes(), key=lambda n: n.text)
    assert [n.text for n in notes] == ["a@x.com not logged in", "b@x.com not logged in"]
    assert all(json.loads(n.data_json)["href"] == f"{lq.LOGINS_PAGE}?queue={q['id']}" for n in notes), notes
    async with _client() as c:
        await _paste(c, "w@x.com:pw1")
        await _until(lambda: len(START.jobs) == 3)
        START.jobs[2].fail(rl.TIMED_OUT)  # the job's own Browserbase window ran out
        await _until(lambda: _queue().finished)
    assert [n.text for n in await _notes() if n.text.startswith("w@")] == ["w@x.com not logged in after 5 min"]


async def case_timeout() -> None:
    START.reset()
    saved = lq.GRACE_S
    lq.GRACE_S = 0.1 - rl.JOB_WINDOW_S  # the deadline 0.1 s after the start
    lq.SETTLE_S, settle = 0.1, lq.SETTLE_S
    try:
        async with _client() as c:
            q = await _paste(c, "t1@x.com:pw1\nt2@x.com:pw2")
            await _until(lambda: len(START.jobs) == 2)  # t1 never ends: timed out, the queue moved on
            assert START.jobs[0]._cancel.is_set()
            START.jobs[1].set_state(rl.STATE_DONE)
            await _until(lambda: _queue().finished)
            v = await _get(c, q["id"])
    finally:
        lq.GRACE_S, lq.SETTLE_S = saved, settle
    e = v["entries"][0]
    assert (e["state"], e["message"], e["live_view_url"]) == (rl.STATE_ERROR, lq.TIMED_OUT, None), v
    assert [n.text for n in await _notes() if n.text.startswith("t")] == ["t1@x.com not logged in after 5 min"]


async def case_timeout_then_done() -> None:
    START.reset()
    saved = lq.GRACE_S, lq.SETTLE_S
    lq.GRACE_S, lq.SETTLE_S = 0.1 - rl.JOB_WINDOW_S, 5.0
    before = len(await _notes())
    try:
        async with _client() as c:
            q = await _paste(c, "s1@x.com:pw1\ns2@x.com:pw2")
            await _until(lambda: len(START.jobs) == 1 and START.jobs[0]._cancel.is_set())
            await asyncio.sleep(0.05)
            assert len(START.jobs) == 1  # no overlap: the next waits for the cancelled one to end
            START.jobs[0].account_id = "222"
            START.jobs[0].set_state(rl.STATE_DONE, "logged in")  # it logged in while winding down
            await _until(lambda: len(START.jobs) == 2)
            START.jobs[1].set_state(rl.STATE_DONE)
            await _until(lambda: _queue().finished)
            v = await _get(c, q["id"])
    finally:
        lq.GRACE_S, lq.SETTLE_S = saved
    assert [(e["state"], e["account_id"]) for e in v["entries"]][0] == (rl.STATE_DONE, "222"), v
    assert len(await _notes()) == before


async def case_cancel() -> None:
    START.reset()
    before = len(await _notes())
    async with _client() as c:
        q = await _paste(c, "k1@x.com:pw1\nk2@x.com:pw2\nk3@x.com:pw3")
        await _until(lambda: len(START.jobs) == 1)
        r = await c.post(f"{Q}/{q['id']}/cancel", headers=COOKIE_A)
        assert r.status_code == 200 and r.json()["state"] == "cancelled", r.text
        assert [e["state"] for e in r.json()["entries"][1:]] == [rl.STATE_CANCELLED] * 2, r.text
        assert all(e.password is None for e in _queue().entries)
        job = START.jobs[0]
        assert job._cancel.is_set()
        job.set_state(rl.STATE_CANCELLED)  # what the job's thread does on its cancel
        await _until(lambda: _queue().finished)
        await asyncio.sleep(0.05)
        v = await _get(c, q["id"])
    assert v["state"] == "cancelled" and len(START.calls) == 1, v
    assert [e["state"] for e in v["entries"]] == [rl.STATE_CANCELLED] * 3, v
    assert len(await _notes()) == before


async def case_busy_and_404() -> None:
    START.reset()
    async with _client() as c:
        r = await c.get(Q, headers=COOKIE_A)
        assert r.status_code == 404, r.text
        q = await _paste(c, "a@x.com:pw1")
        assert (await c.get(Q, headers=COOKIE_A)).json()["id"] == q["id"]
        assert (await c.get(Q, headers=COOKIE_B)).status_code == 404
        r = await c.post(Q, json={"text": "z@x.com:pw9"}, headers=COOKIE_A)
        assert r.status_code == 409 and "pw9" not in r.text, r.text
        for path in (f"{Q}/{q['id']}", f"{Q}/nope"):
            assert (await c.get(path, headers=COOKIE_B)).status_code == 404
        assert (await c.post(f"{Q}/{q['id']}/cancel", headers=COOKIE_B)).status_code == 404
        r = await c.get(f"{Q}/{uuid.uuid4().hex}", headers=COOKIE_A)
        assert r.status_code == 404 and r.json()["detail"] == remote_login_api._NO_QUEUE, r.text
        assert not _queue().cancelled  # B's cancel touched nothing
        await _until(lambda: len(START.jobs) == 1)
        START.jobs[0].set_state(rl.STATE_DONE)
        await _until(lambda: _queue().finished)
        q2 = await _paste(c, "z@x.com:pw9")
        assert q2["id"] != q["id"]
        await _until(lambda: len(START.jobs) == 2)
        START.jobs[1].set_state(rl.STATE_DONE)
        await _until(lambda: _queue().finished)
        assert (await _get(c, q2["id"]))["state"] == "done"
        r = await c.get(Q, headers=COOKIE_A)
        assert (r.json()["id"], r.json()["state"]) == (q2["id"], "done"), r.text
        r = await c.get(f"{Q}/{q['id']}", headers=COOKIE_A)
        assert r.status_code == 404 and "no longer on the relay" in r.json()["detail"], r.text
    assert lq.get(OWNER_A, q["id"]) is None  # the finished one was replaced


async def case_cancelled_replaceable() -> None:
    START.reset()
    async with _client() as c:
        q = await _paste(c, "r1@x.com:pw1\nr2@x.com:pw2")
        await _until(lambda: len(START.jobs) == 1)
        assert (await c.post(f"{Q}/{q['id']}/cancel", headers=COOKIE_A)).status_code == 200
        assert not _queue().finished  # its job has not ended yet
        q2 = await _paste(c, "r3@x.com:pw3")
        assert q2["id"] != q["id"] and (await c.get(Q, headers=COOKIE_A)).json()["id"] == q2["id"]
        await asyncio.sleep(0.05)
        assert len(START.jobs) == 1  # no overlap: r3 waits for the stopped job to end
        START.jobs[0].set_state(rl.STATE_CANCELLED)
        await _until(lambda: len(START.jobs) == 2 and START.jobs[1].email == "r3@x.com")
        START.jobs[1].set_state(rl.STATE_DONE)
        await _until(lambda: _queue().finished)


async def case_replaced_same_email() -> None:
    START.reset()
    async with _client() as c:
        q = await _paste(c, "same@x.com:old-pw1\nother@x.com:pw2")
        await _until(lambda: len(START.jobs) == 1)
        assert (await c.post(f"{Q}/{q['id']}/cancel", headers=COOKIE_A)).status_code == 200
        await _paste(c, "SAME@x.com:new-pw2")
        await asyncio.sleep(0.05)
        assert len(START.jobs) == 1  # the old job still holds the email
        START.jobs[0].set_state(rl.STATE_CANCELLED)
        await _until(lambda: len(START.jobs) == 2)
        assert (START.calls[1]["email"], START.calls[1]["password"]) == ("SAME@x.com", "new-pw2"), START.calls
        START.jobs[1].set_state(rl.STATE_DONE)
        await _until(lambda: _queue().finished)
        assert _queue().entries[0].state == rl.STATE_DONE


async def case_replaced_still_running() -> None:
    START.reset()
    saved, lq.SETTLE_S = lq.SETTLE_S, 0.1
    before = len(await _notes())
    try:
        async with _client() as c:
            q = await _paste(c, "stuck@x.com:pw1")
            await _until(lambda: len(START.jobs) == 1)
            assert (await c.post(f"{Q}/{q['id']}/cancel", headers=COOKIE_A)).status_code == 200
            q2 = await _paste(c, "stuck@x.com:pw-new\nfree@x.com:pw3")
            await _until(lambda: len(START.jobs) == 2)  # stuck never ends: free runs after SETTLE_S
            assert [x["email"] for x in START.calls] == ["stuck@x.com", "free@x.com"], START.calls
            START.jobs[1].set_state(rl.STATE_DONE)
            await _until(lambda: _queue().finished)
            v = await _get(c, q2["id"])
    finally:
        lq.SETTLE_S = saved
        START.jobs[0].set_state(rl.STATE_CANCELLED)
    assert [(e["state"], e["message"]) for e in v["entries"]] == [
        (rl.STATE_ERROR, lq.STILL_ENDING), (rl.STATE_DONE, "")], v
    assert _queue().entries[0].password is None and "pw-new" not in json.dumps(v)
    notes = await _notes()
    assert len(notes) == before + 1 and notes[-1].text == "stuck@x.com not logged in", [n.text for n in notes]


async def case_comma_email_bad_line() -> None:
    START.reset()
    async with _client() as c:
        r = await c.post(Q, json={"text": "creator@example.com,secretA:secretB\nok@x.com:pw1"}, headers=COOKIE_A)
        assert r.status_code == 200, r.text
        q = r.json()
        assert q["bad_lines"] == [{"line": 1, "reason": login_paste.NOT_A_LOGIN}], q
        assert [e["email"] for e in q["entries"]] == ["ok@x.com"], q
        await _until(lambda: len(START.jobs) == 1)
        START.jobs[0].fail("wrong password")
        await _until(lambda: _queue().finished)
        texts = [r.text, json.dumps(await _get(c, q["id"])), (await c.get(Q, headers=COOKIE_A)).text]
    texts += [f"{n.text} {n.data_json}" for n in await _notes()]
    assert not [t for t in texts if "secretA" in t or "secretB" in t], texts
    assert START.calls[0]["email"] == "ok@x.com"


def case_body_gates() -> None:
    START.reset()
    for body in (None, {}, {"text": 5}, ["a@x.com:pw1"]):
        r = A.post(Q, json=body)
        assert r.status_code == 400, (body, r.text)
    r = A.post(Q, json={"text": f"junk {SECRETS[0]}\n\nx@y.com:"})
    assert r.status_code == 400 and SECRETS[0] not in r.text, r.text
    assert r.json()["detail"]["bad_lines"] == [{"line": 1, "reason": login_paste.NOT_A_LOGIN},
                                               {"line": 3, "reason": login_paste.NOT_A_LOGIN}], r.text
    r = A.post(Q, json={"text": "a@x.com:pw1\n" + "x" * remote_login_api.MAX_PASTE})
    assert r.status_code == 413, r.status_code
    saved, sys.modules["playwright"] = sys.modules["playwright"], None  # find_spec → None: not installed
    try:
        r = A.post(Q, json={"text": f"a@x.com:{SECRETS[0]}"})
        assert r.status_code == 501 and SECRETS[0] not in r.text, r.text
    finally:
        sys.modules["playwright"] = saved
    key = os.environ.pop("BROWSERBASE_API_KEY")
    try:
        r = A.post(Q, json={"text": f"a@x.com:{SECRETS[0]}"})
        assert r.status_code == 503 and SECRETS[0] not in r.text, r.text
    finally:
        os.environ["BROWSERBASE_API_KEY"] = key
    assert lq._QUEUES == {} and START.calls == []


def case_principal_gates() -> None:
    START.reset()
    body = {"text": f"a@x.com:{SECRETS[0]}"}
    r = CHAT.post(Q, json=body)
    assert r.status_code == 403 and SECRETS[0] not in r.text, r.text
    assert CHAT.get(f"{Q}/x").status_code == 403 and CHAT.get(Q).status_code == 403
    for client in (ANON, A):  # a bearer alone, and beside the owner's cookie
        r = client.post(Q, json=body, headers=HA)
        assert r.status_code == 403 and SECRETS[0] not in r.text, r.text
        assert client.get(f"{Q}/x", headers=HA).status_code == 403
        assert client.get(Q, headers=HA).status_code == 403
        assert client.post(f"{Q}/x/cancel", headers=HA).status_code == 403
    assert ANON.post(Q, json=body).status_code == 401
    assert lq._QUEUES == {} and START.calls == []
    for path in (Q, f"{Q}/x/cancel"):
        assert any(path.startswith(p) for p in employees._AUDIT_SKIP_PREFIXES)
        assert any(path.startswith(p) for p in chatters._CHATTER_BLOCKED_ADMIN_PREFIXES)


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage() + repr(record.args))


async def case_secrets_nowhere() -> None:
    START.reset()
    START.raise_for = {"b@x.com"}
    async with get_session() as s:
        last = (await s.execute(select(Action.id).order_by(Action.id.desc()).limit(1))).scalar() or 0
    grab, root = _Grab(), logging.getLogger()
    saved = root.level
    root.addHandler(grab)
    root.setLevel(logging.DEBUG)
    try:
        async with _client() as c:
            q = await _paste(c)
            await _until(lambda: len(START.jobs) == 1)
            START.jobs[0].fail("wrong password")
            await _until(lambda: _queue().finished)
            texts = [json.dumps(await _get(c, q["id"]))]
            texts.append((await c.post(f"{Q}/{q['id']}/cancel", headers=COOKIE_A)).text)
    finally:
        root.removeHandler(grab)
        root.setLevel(saved)
    async with get_session() as s:
        rows = (await s.execute(select(Action).where(Action.id > last))).scalars().all()
        notes = (await s.execute(select(AgencyNotification))).scalars().all()
    texts += grab.lines
    texts += [f"{a.action} {a.target_id} {a.payload_json}" for a in rows]
    texts += [f"{n.text} {n.data_json}" for n in notes]
    leaked = [t for t in texts if any(s in t for s in SECRETS)]
    assert not leaked, leaked[:3]
    assert not any("/admin/login" in f"{a.action} {a.target_id}" for a in rows), rows


if __name__ == "__main__":
    _harness.run()
