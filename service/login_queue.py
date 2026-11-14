"""service/login_queue.py — the pasted-logins queue (ultra-mode ticket 11; HTTP: remote_login_api, parser:
login_paste). Per owner, in memory, one login at a time: each entry is a `remote_login.start_login(...,
backend="browserbase")` job on the relay's default proxy, polled until it ends.

- One queue per owner: a new paste while one runs is refused (409); a finished or cancelled one is
  replaced. A replaced queue's job may still be winding down (it still holds its email): the new worker
  waits up to SETTLE_S for it to end before its first login. An entry for an email whose old job is still
  running after that is an error (STILL_ENDING) + notice, never started; the others run.
- A password lives in its entry only until its job starts, the queue is cancelled or the run ends
  (each clears it); it never reaches a status, the DB, the audit, a log line or a notice.
- A job in "otp" shows on the card, which posts the code to /admin/login/remote/{job_id}/otp
  (the job's principal is the owner, so the existing route takes it).
- A job that errors (or a start that raises) leaves an `ultra_needs_you` notice "<email> not logged in"
  and the queue moves on. One not ended within its window + GRACE_S is cancelled, then given SETTLE_S to
  end: its real end is shown (done: no notice); still running or cancelled: an error (TIMED_OUT) + the
  notice "<email> not logged in after 5 min" (the job's own window running out files that text too).
  A job cancelled on its own (Stop on the card) moves on with no notice.
- A relay restart drops every queue: the card shows `interrupted` for an unknown queue id.

The worker is a task on the loop serving the request that pasted (it inherits that request's
context, so start_login's thread links each new account to the owner, as the Add creator card's).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import remote_login
from login_paste import LOGINS_PAGE

log = logging.getLogger(__name__)

POLL_S = 1.5
GRACE_S = 30  # past remote_login.JOB_WINDOW_S: the job is cancelled
SETTLE_S = 30  # after that cancel: wait this long for the job to end before the next login
WAITING = "waiting"
NOT_LOGGED_IN = "{email} not logged in"
NOT_LOGGED_IN_TIMEOUT = "{email} not logged in after 5 min"
TIMED_OUT = "the login did not finish in time"
STILL_ENDING = "the stopped queue's login for this email had not ended yet; paste it again"


@dataclass
class Entry:
    email: str
    password: str | None = field(default=None, repr=False)
    state: str = WAITING
    job_id: str | None = None
    message: str = ""
    live_view_url: str | None = None
    account_id: str | None = None

    def public(self) -> dict[str, Any]:
        return {"email": self.email, "state": self.state, "job_id": self.job_id, "message": self.message,
                "live_view_url": self.live_view_url, "account_id": self.account_id}


@dataclass
class Queue:
    id: str
    owner: str
    entries: list[Entry]
    proxy: str
    cancelled: bool = False
    finished: bool = False

    def state(self) -> str:
        return "cancelled" if self.cancelled else "done" if self.finished else "running"

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "state": self.state(), "entries": [e.public() for e in self.entries]}


_QUEUES: dict[str, Queue] = {}
_TASKS: set[asyncio.Task] = set()  # strong refs until each run ends


class QueueBusy(RuntimeError):
    pass


def current(owner: str) -> Queue | None:
    """The owner's last queue (running or ended), None when none since the relay started."""
    return _QUEUES.get(owner)


def get(owner: str, queue_id: str) -> Queue | None:
    q = current(owner)
    return q if q is not None and q.id == queue_id else None


def start(owner: str, logins: list[tuple[str, str]], proxy: str) -> Queue:
    """A new queue for `owner` running `logins` ((email, password), in order) on `proxy`, its worker
    started on the running loop. QueueBusy: the owner's last queue still runs (not cancelled)."""
    cur = _QUEUES.get(owner)
    if cur is not None and not cur.finished and not cur.cancelled:
        raise QueueBusy("a login queue is already running — wait for it or cancel it")
    q = Queue(id=uuid.uuid4().hex, owner=owner, proxy=proxy,
              entries=[Entry(email=e, password=p) for e, p in logins])
    _QUEUES[owner] = q
    task = asyncio.get_running_loop().create_task(_run(q, cur), name=f"login-queue-{q.id[:8]}")
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return q


def cancel(q: Queue) -> None:
    """Stop the queue: waiting entries cancelled and their passwords dropped, the running job cancelled."""
    q.cancelled = True
    _drop_waiting(q)
    for e in q.entries:
        if e.job_id and (job := remote_login.get_job(e.job_id)) is not None:
            remote_login.cancel(job)


def _drop_waiting(q: Queue) -> None:
    """Every password dropped; the entries not started yet are cancelled."""
    for e in q.entries:
        e.password = None
        if e.state == WAITING:
            e.state = remote_login.STATE_CANCELLED


def _running_emails(q: Queue | None) -> set[str]:
    """The emails `q`'s jobs still log in (lower case): each holds remote_login's per-email lock."""
    if q is None:
        return set()
    return {e.email.lower() for e in q.entries
            if e.job_id and (job := remote_login.get_job(e.job_id)) is not None and not job.is_terminal()}


async def _run(q: Queue, prev: Queue | None = None) -> None:
    try:
        deadline = time.monotonic() + SETTLE_S
        while _running_emails(prev) and time.monotonic() < deadline and not q.cancelled:
            await asyncio.sleep(POLL_S)
        for e in q.entries:
            if q.cancelled:
                break
            if e.email.lower() in _running_emails(prev):
                e.password, e.state, e.message = None, remote_login.STATE_ERROR, STILL_ENDING
                await _notice(q, e)
                continue
            await _one(q, e)
    except Exception:
        log.exception("login queue %s failed", q.id)
    finally:
        _drop_waiting(q)
        q.finished = True


def _mirror(e: Entry, job: remote_login.RemoteLoginJob) -> None:
    s = job.public()
    e.state, e.message, e.live_view_url, e.account_id = s["state"], s["message"], s["live_view_url"], s["account_id"]


async def _one(q: Queue, e: Entry) -> None:
    password, e.password = e.password, None
    e.state = remote_login.STATE_STARTING
    try:
        job = remote_login.start_login(
            email=e.email, password=password or "", principal=q.owner, proxy=q.proxy, proxy_label="",
            proxy_defaulted=True, nickname=None, make_active=True, backend=remote_login.BACKEND_BROWSERBASE)
    except Exception as ex:  # a running login for this email, the Browserbase env, a bad value
        e.state, e.message = remote_login.STATE_ERROR, remote_login.scrub(str(ex), password)
        await _notice(q, e)
        return
    finally:
        password = None  # noqa: F841 — dropped as soon as the job has it
    e.job_id = job.id
    deadline = time.monotonic() + remote_login.JOB_WINDOW_S + GRACE_S
    timed_out = False
    while True:
        _mirror(e, job)
        if job.is_terminal():
            break
        if not timed_out and time.monotonic() > deadline:
            remote_login.cancel(job)  # then wait for its real end: it may still log in, or wind down
            timed_out, deadline = True, time.monotonic() + SETTLE_S
        elif timed_out and time.monotonic() > deadline:
            break
        await asyncio.sleep(POLL_S)
    if timed_out and e.state not in (remote_login.STATE_DONE, remote_login.STATE_ERROR):
        e.state, e.message, e.live_view_url = remote_login.STATE_ERROR, TIMED_OUT, None
    if e.state == remote_login.STATE_ERROR:
        await _notice(q, e, timed_out=e.message in (TIMED_OUT, remote_login.TIMED_OUT))


async def _notice(q: Queue, e: Entry, timed_out: bool = False) -> None:
    text = (NOT_LOGGED_IN_TIMEOUT if timed_out else NOT_LOGGED_IN).format(email=e.email)
    try:
        from notifications_api import Notice, notify  # lazy: notifications_api imports settings
        await notify(q.owner, [Notice("ultra_needs_you", text,
                                      data={"href": f"{LOGINS_PAGE}?queue={q.id}"},
                                      dedupe=f"login_queue:{q.id}:{e.email.lower()}")])
    except Exception:
        log.exception("login queue notice failed (queue=%s)", q.id)
