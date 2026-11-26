from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import platforms
import remote_login
from login_paste import LOGINS_PAGE

log = logging.getLogger(__name__)

POLL_S = 1.5
# past remote_login.JOB_WINDOW_S: the job is cancelled
GRACE_S = 30
# after that cancel: wait for the job to end before the next login
SETTLE_S = 30
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
_TASKS: set[asyncio.Task] = set()


class QueueBusy(RuntimeError):
    pass


def current(owner: str) -> Queue | None:
    return _QUEUES.get(owner)


def get(owner: str, queue_id: str) -> Queue | None:
    q = current(owner)
    return q if q is not None and q.id == queue_id else None


def start(owner: str, logins: list[tuple[str, str]], proxy: str) -> Queue:
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
    q.cancelled = True
    _drop_waiting(q)
    for e in q.entries:
        if e.job_id and (job := remote_login.get_job(e.job_id)) is not None:
            remote_login.cancel(job)


def _drop_waiting(q: Queue) -> None:
    for e in q.entries:
        e.password = None
        if e.state == WAITING:
            e.state = remote_login.STATE_CANCELLED


def _running_emails(q: Queue | None) -> set[str]:
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
            proxy_defaulted=True, nickname=None, make_active=True, backend=remote_login.BACKEND_BROWSERBASE,
            platform=platforms.ONLYFANS.key)
    except Exception as ex:
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
            remote_login.cancel(job)
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
        from notifications_api import Notice, notify
        await notify(q.owner, [Notice("ultra_needs_you", text,
                                      data={"href": f"{LOGINS_PAGE}?queue={q.id}"},
                                      dedupe=f"login_queue:{q.id}:{e.email.lower()}")])
    except Exception:
        log.exception("login queue notice failed (queue=%s)", q.id)
