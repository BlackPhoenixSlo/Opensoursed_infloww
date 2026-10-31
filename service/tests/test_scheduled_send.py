#!/usr/bin/env python3
"""
scheduled_send — one-shot deferred human send (executor-fired).

This is the server-side replacement for the old in-browser local-wait timer:
a chatter schedules a ≤15-min DM, the relay enqueues a `scheduled_jobs` row
(kind="scheduled_send") with run_at + the scheduling chatter's employee id, and
the executor fires it. Because it's a DB row it survives reload and is shared /
cancelable across every chatter on the account.

Cases (all drive the REAL run_once dispatcher → registry wiring exercised):
  case_fires_and_attributes:
      a due job sends via of_client, writes an outbound `messages` row stamped
      with the SCHEDULING chatter's employee id (the cross-chatter attribution
      claim), and the job is marked 'done'.
  case_media_and_ppv_passthrough:
      media_files / price / previews / giphy reach of_client.send_message intact.
  case_empty_payload_skips:
      a payload with no text/media/gif sends nothing and still completes.
  case_run_at_naive_utc:
      the relay's ISO→naive-UTC parse (Z and +offset) matches what the schema
      compares against (datetime.utcnow()).
  case_fansly_account_fires_through_the_shim:
      a Fansly account's job routes through _make_client's platform branch to
      the shim (positional `text` included) and the job ends 'done' — the two
      bugs that left Fansly sends stuck on "sending now…".
  case_attribution_raises_after_send_parks_not_resends:
      send once: the DM went out, then the attribution write raised -> exactly
      1 OF send, the job ends 'error' ("may have sent"), never pending; a
      second run finds nothing to claim.
  case_read_timeout_parks:
      OF's answer never came (curl ReadTimeout: maybe sent) -> job 'error'
      ("may have sent"), 1 attempt at OF, never requeued.
  case_rate_limit_before_send_retries_as_today:
      OF refused it (its rate-limit 400, both tries: nothing sent) -> back to
      'pending' with the retry backoff, no "may have sent".
  case_cancel_in_rate_limit_pause_retries:
      OF's 400, then the run is cancelled during the async pause before the
      retry: nothing was sent, so the job goes back to 'pending', not parked.
  case_cancel_while_send_out_parks:
      the run is cancelled while OF has the send and has not answered (the
      worker thread runs on): job 'error' ("may have sent"), never requeued.
  case_refused_write_then_unrelated_raise_retries:
      a one-shot whose write the proxy refused (handled by the sender), then
      an unrelated raise: nothing was sent -> 'pending', not parked.
  case_may_have_sent_table:
      of_write_paced's per-attempt classifier over the real exception classes:
      OFDenied/OFDeactivated, curl ProxyError, ConnectTimeout, couldn't-connect
      (7), any 4xx (OF's rate-limit 400 too) -> surely not sent; ReadTimeout,
      other ConnectionError, 5xx, no response, a cancel, unknown -> may have.

Run: ./venv/bin/python service/tests/test_scheduled_send.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automations import scheduled_send  # noqa: E402  (force-register the kind)
from automation_executor import enqueue_job, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Employee, Message, ScheduledJob  # noqa: E402

assert scheduled_send is not None  # silence "imported but unused"

# The GENUINE construction seam, grabbed before any case swaps it for a fake.
# `_use_fake` overwrites `ax._make_client` and never restores it, so a case
# that needs the real platform branch (the Fansly one below) cannot recover it
# by reading the attribute at call time — it would get the previous case's fake.
_REAL_MAKE_CLIENT = ax._make_client

OWN_ID = "555"
EMP_ID = 42


class FakeOF:
    """Records the full send_message call so we can assert passthrough."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._next_id = 9_100_000_000_000

    def send_message(self, chat_id, text, *, price=0, locked_text=False,
                     media_files=None, previews=None, tagged_users=None,
                     giphy_id=None, **kw) -> dict:
        self._next_id += 1
        self.sent.append({
            "chat_id": int(chat_id), "text": text, "price": price,
            "locked_text": locked_text, "media_files": list(media_files or []),
            "previews": list(previews or []), "tagged_users": list(tagged_users or []),
            "giphy_id": giphy_id, "auto_tag": kw.get("auto_tag"),
        })
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-13T15:38:00+00:00"}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed() -> None:
    async with get_session() as s:
        if await s.get(Account, OWN_ID) is None:
            s.add(Account(id=OWN_ID))
        if await s.get(Employee, EMP_ID) is None:
            s.add(Employee(id=EMP_ID, display_name="Tess"))


async def _enqueue_due(payload: dict) -> int:
    """Enqueue a scheduled_send job already PAST due so run_once claims it."""
    return await enqueue_job(
        OWN_ID, "scheduled_send",
        payload=payload,
        run_at=datetime.utcnow() - timedelta(seconds=60),
        created_by_employee_id=payload.get("sent_by_employee_id"),
    )


# ── Cases ─────────────────────────────────────────────────────────────

def case_fires_and_attributes():
    fake = _use_fake()
    import asyncio
    asyncio.run(_seed())
    fid = 1111

    job_id = asyncio.run(_enqueue_due({
        "fan_id": fid, "text": "here is the shower", "price": 0,
        "media_files": [], "sent_by_employee_id": EMP_ID,
    }))
    res = asyncio.run(run_once(OWN_ID, "scheduled_send"))

    assert res["status"] == "ok", f"run failed: {res}"
    assert len(fake.sent) == 1, "exactly one send"
    assert fake.sent[0]["chat_id"] == fid and fake.sent[0]["text"] == "here is the shower"

    async def _check():
        async with get_session() as s:
            msgs = (await s.execute(
                select(Message).where(Message.account_id == OWN_ID, Message.fan_id == fid)
            )).scalars().all()
            job = await s.get(ScheduledJob, job_id)
            return msgs, job
    msgs, job = asyncio.run(_check())
    assert len(msgs) == 1 and msgs[0].body, "outbound row persisted with body"
    assert msgs[0].sent_by_employee_id == EMP_ID, \
        f"attributed to the scheduling chatter, got {msgs[0].sent_by_employee_id}"
    assert job is not None and job.status == "done", f"job not done: {job and job.status}"


def case_media_and_ppv_passthrough():
    fake = _use_fake()
    import asyncio
    asyncio.run(_seed())
    fid = 2222
    asyncio.run(_enqueue_due({
        "fan_id": fid, "text": "unlock me", "price": 24.99, "locked_text": True,
        "media_files": [501, 502], "previews": [501], "giphy_id": "abc123",
        "sent_by_employee_id": EMP_ID,
    }))
    res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
    assert res["status"] == "ok", f"run failed: {res}"
    sent = fake.sent[0]
    assert sent["media_files"] == [501, 502], sent
    assert sent["price"] == 24.99 and sent["locked_text"] is True, sent
    assert sent["previews"] == [501] and sent["giphy_id"] == "abc123", sent


def case_manual_deferral_does_not_auto_tag():
    """The composer's =<15-min deferral is a HUMAN send, and the co-performer
    auto-tag is for senders with no operator at the picker.

    This matters only since the tag started landing: the chat body now carries
    `rfTag`, so an auto id here would publicly name a co-performer the operator
    never selected -- while the immediate send (server.py of_send_message) and
    the >15-min OF-queue send, the same button either side of this one, both
    pass auto_tag=False. Derived from the `manual` stamp rather than hardcoded,
    so a job enqueued without it still auto-tags."""
    fake = _use_fake()
    import asyncio
    asyncio.run(_seed())

    asyncio.run(_enqueue_due({
        "fan_id": 3131, "text": "in a bit", "media_files": [501],
        "sent_by_employee_id": EMP_ID, "send_purpose": "manual",
    }))
    assert asyncio.run(run_once(OWN_ID, "scheduled_send"))["status"] == "ok"
    assert fake.sent[0]["auto_tag"] is False, fake.sent[0]

    # No `manual` stamp = not the composer. The auto tag stays on, because the
    # release-form rule is exactly what protects a sender with no human on it.
    fake2 = _use_fake()
    asyncio.run(_enqueue_due({
        "fan_id": 3232, "text": "automated", "media_files": [501],
        "sent_by_employee_id": EMP_ID,
    }))
    assert asyncio.run(run_once(OWN_ID, "scheduled_send"))["status"] == "ok"
    assert fake2.sent[0]["auto_tag"] is True, fake2.sent[0]


def case_empty_payload_skips():
    fake = _use_fake()
    import asyncio
    asyncio.run(_seed())
    asyncio.run(_enqueue_due({
        "fan_id": 3333, "text": "   ", "media_files": [], "giphy_id": None,
        "sent_by_employee_id": EMP_ID,
    }))
    res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
    assert res["status"] == "skipped", f"expected skip, got {res}"
    assert fake.sent == [], "nothing sent for an empty payload"


def case_run_at_naive_utc():
    import server  # noqa: E402 — module-level parse helper
    z = server._run_at_naive_utc("2026-06-13T15:38:00Z")
    assert z.tzinfo is None and z == datetime(2026, 6, 13, 15, 38, 0), z
    off = server._run_at_naive_utc("2026-06-13T15:38:00+02:00")
    assert off.tzinfo is None and off == datetime(2026, 6, 13, 13, 38, 0), off


def case_list_shows_only_human_sends():
    """GET /scheduled-sends lists a human's queued `scheduled_send` rows and
    nothing else. The retired selling engine used to surface its Human Rhythm
    wake here as a text-less `ai_reply` row; a leftover pending row of that kind
    must not put a phantom countdown in the thread."""
    import server  # noqa: E402
    from starlette.requests import Request

    # RESTORE this: _harness.run shares one process, so leaving the registry
    # stubbed would silently hand a fake account to every case added after us.
    _real_get_account = server.account_registry.get_account
    server.account_registry.get_account = lambda a: {"id": a}  # type: ignore[attr-defined]
    soon = datetime.utcnow() + timedelta(minutes=4)

    async def go():
        await _seed()
        await enqueue_job(OWN_ID, "scheduled_send",
                          payload={"fan_id": 111, "text": "hey you"}, run_at=soon)
        # A leftover wake of the retired engine (historical kind name).
        await enqueue_job(OWN_ID, "ai_chatter",
                          payload={"only_fan_ids": [111], "rhythm_resume": True},
                          run_at=soon)

        req = Request({"type": "http", "method": "GET", "path": "/",
                       "headers": [(b"x-account-id", OWN_ID.encode())],
                       "query_string": b""})
        got = (await server.list_scheduled_sends(req, fan_id=111))["list"]
        assert [r["kind"] for r in got] == ["scheduled_send"], got
        assert got[0]["text"] == "hey you" and got[0]["fan_id"] == 111, got

    import asyncio
    try:
        asyncio.run(go())
    finally:
        server.account_registry.get_account = _real_get_account  # type: ignore[attr-defined]


def case_fansly_account_fires_through_the_shim():
    """A Fansly account's deferred send must reach the SHIM, not an OFClient.

    Two bugs made every Fansly scheduled send hang on "sending now…" forever:
    `ax._make_client` had no platform branch (server._load_client did), so the
    executor built an OFClient for an account with no OF session — FileNotFound,
    three retries, job parked; and the shim declared `text` keyword-only while
    this automation (like OFClient) passes it positionally — TypeError even once
    routed. The ghost bubble stays on screen the whole time because the list
    endpoint shows `pending` rows.

    So this case deliberately does NOT patch `_make_client` — the platform
    branch inside it is the thing under test. It stubs the two seams that
    branch consults: the account registry's platform, and fansly_backend's
    client pool.
    """
    import asyncio
    import sys
    import types

    asyncio.run(_seed())
    fid = 4444

    class FakeShim:
        """Mirrors FanslyShimClient.send_message's real signature, including the
        keyword-only tail — so a positional `text` here fails exactly as the
        shipped shim did."""
        def __init__(self):
            self.sent = []

        def send_message(self, chat_id, text=None, *, locked_text=None, price=0,
                         media_files=None, previews=None, is_forward=False,
                         reply_to_message_id=None, tagged_users=None,
                         giphy_id=None, auto_tag=False, **_ignored):
            self.sent.append({"chat_id": chat_id, "text": text, "giphy_id": giphy_id})
            return {"id": 9_200_000_000_001, "text": text,
                    "createdAt": "2026-06-13T15:38:00+00:00"}

    shim = FakeShim()
    fake_backend = types.ModuleType("fansly_backend")
    fake_backend.get_client = lambda account_id: shim          # type: ignore[attr-defined]
    fake_backend.drop = lambda account_id=None: None           # type: ignore[attr-defined]

    prev_make_client = ax._make_client
    real_get_platform = ax.account_registry.get_platform
    real_module = sys.modules.get("fansly_backend")
    ax._make_client = _REAL_MAKE_CLIENT   # type: ignore[attr-defined]
    ax.account_registry.get_platform = (                       # type: ignore[attr-defined]
        lambda a: "fansly" if a == OWN_ID else "onlyfans")
    sys.modules["fansly_backend"] = fake_backend
    try:
        asyncio.run(_enqueue_due({
            "fan_id": fid, "text": "want to see the rest?",
            "sent_by_employee_id": EMP_ID, "send_purpose": "manual",
        }))
        res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
        assert res["status"] == "ok", f"fansly send did not fire: {res}"
        assert len(shim.sent) == 1, f"shim never called: {shim.sent}"
        assert shim.sent[0]["text"] == "want to see the rest?", shim.sent[0]

        # ...and the job must be CONSUMED. A job left 'pending' is precisely what
        # keeps the "sending now…" ghost on screen tick after tick.
        async def _job():
            async with get_session() as s:
                return (await s.execute(
                    select(ScheduledJob).where(ScheduledJob.account_id == OWN_ID)
                    .order_by(ScheduledJob.id.desc())
                )).scalars().first()
        job = asyncio.run(_job())
        assert job is not None and job.status == "done", \
            f"job left {job and job.status} — the ghost bubble never clears"
    finally:
        # _harness.run shares one process: leaving these stubbed would hand a
        # phantom Fansly account to every case added after this one.
        ax._make_client = prev_make_client                      # type: ignore[attr-defined]
        ax.account_registry.get_platform = real_get_platform    # type: ignore[attr-defined]
        if real_module is None:
            sys.modules.pop("fansly_backend", None)
        else:
            sys.modules["fansly_backend"] = real_module


class RaisingOF(FakeOF):
    """send_message raises `exc` (after recording the attempt) instead of answering."""

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc, self.attempts = exc, 0

    def send_message(self, chat_id, text, **kw) -> dict:
        self.attempts += 1
        raise self.exc


async def _job_row(job_id: int) -> ScheduledJob:
    async with get_session() as s:
        return await s.get(ScheduledJob, job_id)


def case_attribution_raises_after_send_parks_not_resends():
    import asyncio
    fake = _use_fake()
    asyncio.run(_seed())
    real = scheduled_send.write_outbound_attribution

    async def boom(**_kw):
        raise RuntimeError("attribution insert failed")
    scheduled_send.write_outbound_attribution = boom
    try:
        job_id = asyncio.run(_enqueue_due({
            "fan_id": 4141, "text": "sent then broke", "sent_by_employee_id": EMP_ID,
            "send_purpose": "manual"}))
        res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
        again = asyncio.run(run_once(OWN_ID, "scheduled_send"))
    finally:
        scheduled_send.write_outbound_attribution = real
    assert res["status"] == "error", res
    assert len(fake.sent) == 1, f"one OF send, got {len(fake.sent)}"
    job = asyncio.run(_job_row(job_id))
    assert job.status == "error", f"job {job.status}: a sent DM must not be retried"
    assert "may have sent" in (job.last_error or ""), job.last_error
    assert again.get("reason") == "no_job", again
    assert len(fake.sent) == 1, "nothing resent"


def case_read_timeout_parks():
    import asyncio
    from curl_cffi import requests as curl
    fake = RaisingOF(curl.exceptions.ReadTimeout("Operation timed out after 30001 milliseconds"))
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    asyncio.run(_seed())
    job_id = asyncio.run(_enqueue_due({
        "fan_id": 4242, "text": "no answer", "sent_by_employee_id": EMP_ID,
        "send_purpose": "manual"}))
    res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
    assert res["status"] == "error", res
    assert fake.attempts == 1, fake.attempts
    job = asyncio.run(_job_row(job_id))
    assert job.status == "error", f"job {job.status}: OF may have taken it"
    assert "may have sent" in (job.last_error or ""), job.last_error


def _rate_limit_400(fan_id: int):
    from types import SimpleNamespace
    from of_client import OFAPIError
    return OFAPIError(f'400 for https://onlyfans.com/api2/v2/chats/{fan_id}/messages\n'
                      '{"error":{"code":0,"message":"Please allow 10 seconds"}}',
                      response=SimpleNamespace(status_code=400))


class _RateLimitPause:
    """of_write_paced's rate-limit pause (11 s) as `pause_s`: of_write_with_retry,
    which it calls by module name, wrapped (the retry logic itself unchanged)."""

    def __init__(self, pause_s: float) -> None:
        self.pause_s, self.real = pause_s, ax.of_write_with_retry

    def __enter__(self):
        real, pause_s = self.real, self.pause_s
        ax.of_write_with_retry = lambda fn, *, tries, **_: real(  # type: ignore[assignment]
            fn, tries=tries, pause_s=pause_s)
        return self

    def __exit__(self, *_exc) -> None:
        ax.of_write_with_retry = self.real


def case_rate_limit_before_send_retries_as_today():
    import asyncio
    fake = RaisingOF(_rate_limit_400(4343))
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    asyncio.run(_seed())
    with _RateLimitPause(0.0):
        job_id = asyncio.run(_enqueue_due({
            "fan_id": 4343, "text": "rate limited", "sent_by_employee_id": EMP_ID,
            "send_purpose": "manual"}))
        res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
    assert res["status"] == "error", res
    assert fake.attempts == 2, f"of_write_with_retry's two tries, got {fake.attempts}"
    job = asyncio.run(_job_row(job_id))
    assert job.status == "pending", f"job {job.status}: nothing was sent, retry as today"
    assert job.run_at > datetime.utcnow(), "requeued with the backoff"
    assert "may have sent" not in (job.last_error or ""), job.last_error
    assert "allow 10 seconds" in (job.last_error or ""), job.last_error


async def _cancel_once(pred, timeout_s: float = 30.0) -> None:
    """Run the due scheduled_send, cancel it once `pred()` holds; it must re-raise."""
    import asyncio
    ax._write_gates.clear()   # no 11 s spacing behind the previous case's send
    task = asyncio.create_task(run_once(OWN_ID, "scheduled_send"))
    t0 = asyncio.get_running_loop().time()
    while not pred():
        assert not task.done(), task.result()
        assert asyncio.get_running_loop().time() - t0 < timeout_s, "never got there"
        await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    raise AssertionError("run_once must re-raise the cancel")


def case_cancel_in_rate_limit_pause_retries():
    import asyncio
    fake = RaisingOF(_rate_limit_400(4444))
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    asyncio.run(_seed())
    job_id = asyncio.run(_enqueue_due({
        "fan_id": 4444, "text": "cancelled in the pause", "sent_by_employee_id": EMP_ID,
        "send_purpose": "manual"}))
    with _RateLimitPause(30.0):
        asyncio.run(_cancel_once(lambda: fake.attempts == 1))
    assert fake.attempts == 1, fake.attempts
    job = asyncio.run(_job_row(job_id))
    assert job.status == "pending", f"job {job.status}: OF refused it, nothing was sent"
    assert "may have sent" not in (job.last_error or ""), job.last_error


def case_cancel_while_send_out_parks():
    import asyncio
    import threading
    release = threading.Event()

    class HangingOF(FakeOF):
        def __init__(self) -> None:
            super().__init__()
            self.out = threading.Event()

        def send_message(self, chat_id, text, **kw) -> dict:
            self.out.set()
            release.wait(30)   # OF has it; its answer has not come back
            return super().send_message(chat_id, text, **kw)

    fake = HangingOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    asyncio.run(_seed())
    job_id = asyncio.run(_enqueue_due({
        "fan_id": 4545, "text": "cancelled while out", "sent_by_employee_id": EMP_ID,
        "send_purpose": "manual"}))
    try:
        asyncio.run(_cancel_once(fake.out.is_set))
    finally:
        release.set()
    job = asyncio.run(_job_row(job_id))
    assert job.status == "error", f"job {job.status}: OF may have taken it"
    assert "may have sent" in (job.last_error or ""), job.last_error


def case_refused_write_then_unrelated_raise_retries():
    import asyncio
    from automation_registry import get_automation, register
    from curl_cffi import requests as curl
    fake = RaisingOF(curl.exceptions.ProxyError("CONNECT tunnel failed, response 403"))
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    asyncio.run(_seed())
    real = get_automation("scheduled_send")

    async def sender(account_id, payload, *, run_id):
        client = ax._make_client(account_id)
        try:   # a sender that handles a refused write and goes on
            await ax.of_write_paced(account_id, lambda: client.send_message(1, "x"),
                                    send_purpose="manual")
        except curl.exceptions.ProxyError:
            pass
        raise RuntimeError("database is locked")   # unrelated, after nothing was sent

    register("scheduled_send")(sender)
    ax._write_gates.clear()
    try:
        job_id = asyncio.run(_enqueue_due({"fan_id": 4646, "text": "refused then broke",
                                           "send_purpose": "manual"}))
        res = asyncio.run(run_once(OWN_ID, "scheduled_send"))
    finally:
        register("scheduled_send")(real)
    assert res["status"] == "error", res
    assert fake.attempts == 1, fake.attempts
    job = asyncio.run(_job_row(job_id))
    assert job.status == "pending", f"job {job.status}: nothing was sent, retry as today"
    assert "may have sent" not in (job.last_error or ""), job.last_error


def case_may_have_sent_table():
    import asyncio
    from types import SimpleNamespace
    from curl_cffi import requests as curl
    from of_client import OFAPIError, OFDeactivatedError, OFDeniedError

    def http(status: int) -> OFAPIError:
        return OFAPIError(f"{status} for https://onlyfans.com/api2/v2/chats/1/messages",
                          response=SimpleNamespace(status_code=status))
    couldnt = curl.exceptions.ConnectionError("Failed to connect to proxy")
    couldnt.code = 7   # curl_cffi.const.CurlECode.COULDNT_CONNECT
    rows = [
        (OFDeniedError("refused: POST /api2/v2/users/logout"), False),
        (OFDeactivatedError("refused: POST /chats/1/messages (Creator deactivated)"), False),
        (curl.exceptions.ProxyError("CONNECT tunnel failed, response 403"), False),
        (curl.exceptions.ConnectTimeout("Connection timed out after 10001 ms"), False),
        (couldnt, False),
        (_rate_limit_400(1), False),
        (http(403), False),
        (http(404), False),
        (Exception("400 ... Please Allow 10 seconds before"), False),   # wrapped rate limit
        (curl.exceptions.ReadTimeout("Operation timed out after 30000 ms"), True),
        (curl.exceptions.Timeout("timed out"), True),
        (curl.exceptions.ConnectionError("Connection reset by peer"), True),
        (curl.exceptions.SSLError("SSL_read: unexpected eof"), True),
        (ConnectionError("proxy timed out"), True),
        (TimeoutError(), True),
        (http(500), True),
        (http(502), True),
        (OFAPIError("no response"), True),
        (asyncio.CancelledError(), True),
        (RuntimeError("attribution insert failed"), True),   # unknown: conservative
    ]
    for e, want in rows:
        assert ax._may_have_sent(e) is want, (repr(e), want)


if __name__ == "__main__":
    _harness.run(
        case_fires_and_attributes,
        case_media_and_ppv_passthrough,
        case_manual_deferral_does_not_auto_tag,
        case_empty_payload_skips,
        case_run_at_naive_utc,
        case_list_shows_only_human_sends,
        case_fansly_account_fires_through_the_shim,
        case_attribution_raises_after_send_parks_not_resends,
        case_read_timeout_parks,
        case_rate_limit_before_send_retries_as_today,
        case_cancel_in_rate_limit_pause_retries,
        case_cancel_while_send_out_parks,
        case_refused_write_then_unrelated_raise_retries,
        case_may_have_sent_table,
    )
