"""
Web Push sender (runtime; push_decide is its pure half, push_notice the frame -> notice port).
design.md B1 + amendments 1-2: every enabled, in-scope, deduped notice goes to every live
subscription; the service worker dedupes at display time.

  offer(frame)   events._fanout's hook, on the loop thread: put_nowait on the inbox (INBOX_MAX,
                 drops oldest). Never awaits, never raises out. `assignment_changed` /
                 `sessions_revoked` clear push_scope's cache instead.
  dispatcher     one task: notices_for -> per in-memory sub: types + platform (no I/O), then scope
                 (dead -> prune), then the tag dedupe -> its worker shard (WORKER_MAX, drops
                 oldest). The tag is claimed in the sub's Seen here, so a re-offer queued meanwhile
                 is dropped. It stays only if the push service accepts; every other end (retries
                 exhausted, RETRY_TASKS full, a dropped queue item, a failed scope read, a send-time
                 skip) un-claims it, so the next purchase re-offer pushes again. An accepted
                 purchase-lane tag (the lane a restart re-walks) is persisted in `push_sent`;
                 start() reloads it, so the re-walk re-pushes nothing.
  workers        N_WORKERS, a sub always on the same one. Re-check session + scope + types right
                 before the send, encrypt (aes128gcm), POST with VAPID. 404/410 prune.
                 429/5xx/transport: a delayed retry task (1 s / 4 s, Retry-After <= 30 s, at most
                 RETRY_TASKS pending) re-queues it; a worker never sleeps. Order is kept per sub
                 except around a retry: later notices go out while it waits (queues are not held).
  vapid()        the P-256 key: env VAPID_PRIVATE_KEY (PEM or b64url raw), else VAPID_KEY_FILE,
                 else service/secrets/vapid_private.pem (bind-mounted, in ae-backup), written once
                 (0600). Never rotate it: every subscription is bound to its public half.
  disabled()     why push is off: no usable VAPID subject host (VAPID_SUBJECT, else SITE_URL;
                 empty or localhost: Apple refuses it). Logged once; /push/key answers 503.

Counters: stats() -> events.sse_stats()['push'].
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import ipaddress
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import events_decide as ed
import push_decide as pd
import push_notice as pn
import push_scope

log = logging.getLogger("of-relay.push")

N_WORKERS = 8
INBOX_MAX = 20000
WORKER_MAX = 2000
RETRY_TASKS = 1000
TTL_S = 14400
JWT_CACHE_S = 3600
JWT_EXP_S = 12 * 3600
PLATFORM_TTL_S = 60.0
SENT_PRUNE_S = 3600
RESCOPE = frozenset({"assignment_changed", "sessions_revoked"})
_DEFAULT_KEY = Path(__file__).resolve().parent / "secrets" / "vapid_private.pem"


@dataclass(slots=True)
class Sub:
    id: str
    endpoint: str
    p256dh: str
    auth: str
    kind: str                       # 'user' | 'chatter'
    principal_id: str
    issued_ms: int
    types: frozenset
    platforms: dict
    seen: pd.Seen = field(default_factory=pd.Seen)


_subs: dict[str, Sub] = {}
_inbox: asyncio.Queue | None = None
_workers: list[asyncio.Queue] = []
_tasks: set[asyncio.Task] = set()
_retries: set[asyncio.Task] = set()
_client: Any = None
_db_warned = False
_disabled: str | None = None
_platforms: dict[str, tuple[float, str]] = {}
_lat_ms: collections.deque = collections.deque(maxlen=1000)
_n = collections.Counter()
HOSTS = pd.parse_hosts(os.environ.get("PUSH_ENDPOINT_HOSTS"))


# ── hot path ──

def offer(frame: dict) -> None:
    """events._fanout's one line (always on the loop thread: events.publish hops there first).
    O(1), no await, never raises."""
    try:
        k = ed.first_key(frame)
        if k in RESCOPE:
            push_scope.clear()
        elif _inbox is not None and k in pn.TYPES and _subs:
            _put(_inbox, (time.monotonic(), frame))
    except Exception:
        log.debug("push offer failed", exc_info=True)


def _put(q: asyncio.Queue, item: Any, on_drop: Any = None) -> None:
    """put_nowait; a full queue drops its oldest item (counted, handed to `on_drop`)."""
    try:
        q.put_nowait(item)
        return
    except asyncio.QueueFull:
        pass
    _n["dropped"] += 1
    with contextlib.suppress(asyncio.QueueEmpty):
        old = q.get_nowait()
        if on_drop is not None:
            on_drop(old)
    with contextlib.suppress(asyncio.QueueFull):
        q.put_nowait(item)


class _Job(NamedTuple):
    """One notice for one sub on a worker queue."""
    t0: float                       # monotonic, when offer() saw the frame
    sub_id: str
    notice: pn.Notice
    attempt: int                    # 0, then each retry
    durable: bool                   # purchase lane: persist in push_sent once accepted


def _to_worker(job: _Job) -> None:
    _put(_workers[pd.shard(job.sub_id, N_WORKERS)], job, _release)


def _release(job: _Job) -> None:
    """Un-claim a job's tag: it ended without the push service accepting it."""
    sub = _subs.get(job.sub_id)
    if sub is not None:
        sub.seen.discard(job.notice.tag)


def _spawn(coro: Any, bag: set) -> asyncio.Task:
    t = asyncio.get_running_loop().create_task(coro)
    bag.add(t)
    t.add_done_callback(bag.discard)
    return t


# ── dispatcher + workers ──

async def _platform(aid: str) -> str:
    hit = _platforms.get(aid)
    now = time.monotonic()
    if hit is None or now - hit[0] > PLATFORM_TTL_S:
        import accounts
        try:
            hit = (now, await asyncio.to_thread(accounts.get_platform, aid))     # meta.json read
        except Exception:
            hit = (now, "onlyfans")
        _platforms[aid] = hit
    return hit[1]


async def _scope(sub: Sub) -> frozenset | None | bool:
    """push_scope.accounts_for, or False on a read error (skip, never prune)."""
    try:
        return await push_scope.accounts_for(sub.kind, sub.principal_id, sub.issued_ms)
    except Exception:
        log.warning("push scope read failed sub=%s", sub.id, exc_info=True)
        return False


async def _dispatch() -> None:
    assert _inbox is not None
    while True:
        t0, frame = await _inbox.get()
        try:
            notices = pn.notices_for(frame)
            if not notices:
                continue
            durable = "purchase_notified" in frame       # the lane a restart re-walks
            plat = {n.account_id: await _platform(n.account_id) for n in notices}
            for sub in list(_subs.values()):
                mine = [n for n in notices if pd.wanted(sub, n, plat[n.account_id])]
                if not mine:
                    continue                             # type / platform off: no scope read
                accounts = await _scope(sub)
                if accounts is None:
                    await prune(sub.id, "dead session")
                    continue
                if accounts is False:
                    continue
                now = time.monotonic()
                for n in mine:
                    if pd.should_push(sub, n, accounts, plat[n.account_id], sub.seen, now):
                        sub.seen.add(n.tag, now)         # claimed while in flight
                        _to_worker(_Job(t0, sub.id, n, 0, durable))
        except Exception:
            log.exception("push dispatch failed")


async def _work(q: asyncio.Queue) -> None:
    while True:
        job = await q.get()
        sub = _subs.get(job.sub_id)
        if sub is None:
            continue
        try:
            await _deliver(sub, job)
        except Exception:
            log.exception("push deliver failed sub=%s", job.sub_id)
            _release(job)


async def _deliver(sub: Sub, job: _Job) -> None:
    n = job.notice
    accounts = await _scope(sub)                # send-time re-check: session, scope, types
    if accounts is None:
        await prune(sub.id, "dead session")
        return
    if accounts is False or not pd.should_push(sub, n, accounts, await _platform(n.account_id), None):
        _n["skipped"] += 1
        _release(job)
        return
    status, retry_after = await _send(sub, n)
    verdict = pd.outcome(status)
    if verdict == "ok":
        _n["sent"] += 1
        _lat_ms.append((time.monotonic() - job.t0) * 1000)
        if job.durable:
            await _record_sent(sub.id, n.tag)
    elif verdict == "retry" and (delay := pd.retry_delay(job.attempt, retry_after)) is not None \
            and len(_retries) < RETRY_TASKS:
        _n["retries"] += 1
        _spawn(_retry_later(delay, job._replace(attempt=job.attempt + 1)), _retries)
    else:
        _release(job)
        await _settle(sub, status, verdict)


async def _retry_later(delay: float, job: _Job) -> None:
    await asyncio.sleep(delay)
    if _workers:
        _to_worker(job)


async def _settle(sub: Sub, status: int | None, verdict: str) -> None:
    """A send that won't be retried: prune a gone sub, else count and log the failure."""
    if verdict == "prune":
        await prune(sub.id, f"push service {status}")
        return
    _n["failed"] += 1
    if status == 403:
        _n["forbidden"] += 1
    log.warning("push failed sub=%s status=%s", sub.id, status)


def wire(n: pn.Notice) -> bytes:
    """The plaintext push body: compact UTF-8 JSON (a lone surrogate becomes "?")."""
    return json.dumps(pn.payload(n), separators=(",", ":"), ensure_ascii=False).encode("utf-8", "replace")


async def _send(sub: Sub, n: pn.Notice) -> tuple[int | None, str | None]:
    """One encrypted POST of `n` to `sub`: (status | None on transport error, Retry-After).
    `_client` is set (start() before any worker; send_test checks); endpoints were vetted by
    PUT and by start()."""
    import httpx
    body = encrypt(sub, wire(n))
    headers = {**vapid_headers(sub.endpoint), "TTL": str(TTL_S), "Urgency": pn.urgency(n),
               "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream"}
    try:
        r = await _client.post(sub.endpoint, content=body, headers=headers)
    except httpx.HTTPError:
        return None, None
    return r.status_code, r.headers.get("retry-after")


def encrypt(sub: Sub, data: bytes) -> bytes:
    import http_ece
    from cryptography.hazmat.primitives.asymmetric import ec
    return http_ece.encrypt(data, private_key=ec.generate_private_key(ec.SECP256R1()),
                            dh=b64d(sub.p256dh), auth_secret=b64d(sub.auth), version="aes128gcm")


def b64d(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── persistence ──

async def _record_sent(sub_id: str, tag: str) -> None:
    """Persist an accepted purchase-lane tag. Never raises: a locked DB logs once and the
    in-memory Seen still dedupes until a restart."""
    global _db_warned
    from sqlalchemy.exc import IntegrityError
    from db.engine import get_session
    from db.models import PushSent
    try:
        async with get_session() as s:
            s.add(PushSent(sub_id=sub_id, tag=tag, sent_at=datetime.utcnow()))
    except IntegrityError:
        pass
    except Exception:
        if not _db_warned:
            _db_warned = True
            log.warning("push_sent write failed (logged once): restart dedupe degraded", exc_info=True)


async def _prune_sent() -> int:
    from sqlalchemy import delete
    from db.engine import get_session
    from db.models import PushSent
    async with get_session() as s:
        r = await s.execute(delete(PushSent).where(
            PushSent.sent_at < datetime.utcnow() - timedelta(seconds=pd.DEDUPE_TTL_S)))
    return r.rowcount or 0


async def _prune_sent_loop() -> None:
    while True:
        await asyncio.sleep(SENT_PRUNE_S)
        with contextlib.suppress(Exception):
            await _prune_sent()


# ── subscriptions (push_api's writes land here after the DB) ──

def sub_from_row(r: Any) -> Sub:
    try:
        types = frozenset(json.loads(r.types or "[]"))
    except (ValueError, TypeError):
        types = frozenset()
    try:
        platforms = json.loads(r.platforms or "{}")
    except (ValueError, TypeError):
        platforms = {}
    return Sub(r.id, r.endpoint, r.p256dh, r.auth, r.principal_kind, r.principal_id, int(r.issued_ms),
               types, platforms if isinstance(platforms, dict) else {})


def upsert(sub: Sub) -> None:
    old = _subs.get(sub.id)
    if old is not None:
        sub.seen = old.seen
    _subs[sub.id] = sub


def owned(sub_id: str, kind: str, principal_id: str) -> Sub | None:
    """The live sub `sub_id` when it belongs to (kind, principal_id), else None."""
    sub = _subs.get(sub_id)
    return sub if sub is not None and (sub.kind, sub.principal_id) == (kind, principal_id) else None


def forget(sub_id: str) -> None:
    _subs.pop(sub_id, None)


async def prune(sub_id: str, why: str) -> None:
    """Delete the row and the memory entry."""
    from sqlalchemy import delete
    from db.engine import get_session
    from db.models import PushSubscription
    _subs.pop(sub_id, None)
    _n["pruned"] += 1
    log.info("push sub pruned id=%s (%s)", sub_id, why)
    with contextlib.suppress(Exception):
        async with get_session() as s:
            await s.execute(delete(PushSubscription).where(PushSubscription.id == sub_id))


_TEST_REASONS = {"ok": "accepted", "prune": "subscription gone at the push service (removed); reopen the app",
                 "retry": "push service unavailable, try again"}


async def send_test(sub_id: str, delay_s: float) -> dict:
    """One visible test notice to `sub_id` after `delay_s`, past every gate but the sub's own
    existence; one attempt. -> {status, reason} as the push service answered."""
    from brand import BRAND_NAME
    await asyncio.sleep(max(0.0, delay_s))
    sub = _subs.get(sub_id)
    if sub is None:
        return {"status": None, "reason": "subscription gone"}
    if _client is None:
        _n["skipped"] += 1
        return {"status": None, "reason": "push is stopped"}
    n = pn.Notice(f"test-{uuid.uuid4().hex[:12]}", "", "test", f"{BRAND_NAME} test",
                  "Push works with the app closed.", "/", "test")
    status, _ = await _send(sub, n)
    verdict = pd.outcome(status)
    if verdict == "ok":
        _n["sent"] += 1
    else:
        await _settle(sub, status, verdict)
    reason = ("transport error" if status is None
              else "push service refused the VAPID key (403); reopen the app to resubscribe" if status == 403
              else _TEST_REASONS.get(verdict, f"push service answered {status}"))
    return {"status": status, "reason": reason}


# ── VAPID ──

_vapid: Any = None
_jwt: dict[str, tuple[float, dict]] = {}


def _key_path() -> Path:
    return Path(os.environ.get("VAPID_KEY_FILE", "").strip() or _DEFAULT_KEY)


def vapid() -> Any:
    global _vapid
    if _vapid is not None:
        return _vapid
    from py_vapid import Vapid02
    env = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if env:
        _vapid = Vapid02.from_pem(env.encode()) if "BEGIN" in env else Vapid02.from_raw(env.encode())
        return _vapid
    path = _key_path()
    if path.exists():
        _vapid = Vapid02.from_pem(path.read_bytes())
        return _vapid
    v = Vapid02()
    v.generate_keys()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(v.private_pem())
    log.warning("VAPID key generated at %s: back it up, never rotate or lose it", path)
    _vapid = v
    return v


def public_key() -> str:
    """The b64url raw (uncompressed point) public key, the browser's applicationServerKey."""
    import base64
    from cryptography.hazmat.primitives import serialization
    raw = vapid().public_key.public_bytes(serialization.Encoding.X962,
                                          serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subject() -> tuple[str | None, str]:
    """(the VAPID `sub`, "") or (None, why push is off)."""
    s = os.environ.get("VAPID_SUBJECT", "").strip()
    if s:
        host = s.partition("@")[2] if s.startswith("mailto:") else urlsplit(s).hostname or ""
    else:
        host = urlsplit(os.environ.get("SITE_URL", "").strip()).hostname or ""
        s = f"mailto:admin@{host}"
    host = host.strip().lower().rstrip(".")
    try:
        loop = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loop = False
    if not host or loop:
        return None, "push is off: set VAPID_SUBJECT (mailto:you@yourdomain) or SITE_URL on the relay"
    return s, ""


def disabled() -> str | None:
    return _disabled


def vapid_headers(endpoint: str) -> dict:
    u = urlsplit(endpoint)
    aud = f"{u.scheme}://{u.netloc}"
    hit = _jwt.get(aud)
    now = time.monotonic()
    if hit is None or now - hit[0] > JWT_CACHE_S:
        hit = (now, vapid().sign({"aud": aud, "sub": subject()[0], "exp": int(time.time()) + JWT_EXP_S}))
        _jwt[aud] = hit
    return hit[1]


# ── lifecycle + stats ──

async def start() -> None:
    """server startup: subject check, the key, the HTTP client, the subscriptions + their sent
    tags, the tasks. A row whose endpoint PUSH_ENDPOINT_HOSTS rejects is skipped in memory and
    KEPT in the DB (the env replaces the default list: one added host must not wipe every
    FCM/Apple sub); counted in stats()['off_hosts'], one warning. Idempotent."""
    global _inbox, _workers, _client, _disabled
    if _inbox is not None:
        return
    sub, why = subject()
    if sub is None:
        _disabled = why
        log.error("WEB PUSH DISABLED: %s", why)
        return
    try:
        vapid()
    except Exception as e:
        _disabled = f"push is off: VAPID key unusable ({e.__class__.__name__})"
        log.exception("WEB PUSH DISABLED: VAPID key unusable")
        return
    _disabled = None
    import httpx
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import PushSent, PushSubscription
    _client = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(max_connections=32),
                                follow_redirects=False)
    with contextlib.suppress(Exception):
        await _prune_sent()
    async with get_session() as s:
        rows = (await s.execute(select(PushSubscription))).scalars().all()
        sent = (await s.execute(select(PushSent).order_by(PushSent.sent_at))).scalars().all()
    _subs.clear()
    off = 0
    for r in rows:
        if pd.endpoint_allowed(r.endpoint, HOSTS):
            upsert(sub_from_row(r))
        else:
            off += 1
    _n["off_hosts"] = off
    if off:
        log.warning("push: %d subscriptions skipped (kept in the DB): endpoint host not in "
                    "PUSH_ENDPOINT_HOSTS", off)
    now, wall = time.monotonic(), datetime.utcnow()
    for r in sent:
        if (sub_ := _subs.get(r.sub_id)) is not None:
            sub_.seen.add(r.tag, now - (wall - r.sent_at).total_seconds())
    _workers = [asyncio.Queue(maxsize=WORKER_MAX) for _ in range(N_WORKERS)]
    _inbox = asyncio.Queue(maxsize=INBOX_MAX)
    _spawn(_dispatch(), _tasks)
    _spawn(_prune_sent_loop(), _tasks)
    for q in _workers:
        _spawn(_work(q), _tasks)
    log.info("push started subs=%d sent_tags=%d", len(_subs), len(sent))


async def stop() -> None:
    global _inbox, _client
    _inbox = None
    for t in [*_tasks, *_retries]:
        t.cancel()
    for t in [*_tasks, *_retries]:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t
    _tasks.clear()
    _retries.clear()
    _workers.clear()
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.aclose()
    _client = None


def stats() -> dict:
    lat = sorted(_lat_ms)
    return {"disabled": _disabled, "subs": len(_subs),
            **{k: _n[k] for k in ("sent", "pruned", "dropped", "failed", "forbidden", "retries", "skipped",
                                  "off_hosts")},
            "inbox": _inbox.qsize() if _inbox is not None else 0,
            "queued": sum(q.qsize() for q in _workers), "retry_pending": len(_retries),
            "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))]) if lat else None}
