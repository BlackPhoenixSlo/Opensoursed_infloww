"""service/of_pacing.py — background OnlyFans list walks: paced per Creator, one retry on
OF's 429; and the relay's one "a person is on this Creator" signal (the hourly link prewarm
and the vault collector read it).

Why (measured on AE, 18 h to 2026-11-05): OF answered "Too many requests. Please allow 1
seconds" 281 times, every one to a background walk (promotions 121, /users/list 148,
payouts 11), none to a click. The walks paged as fast as OF answered.

  walk(account_id, kind, run)
      Runs `run()` as a background walk: inside it, every OFClient GET goes through
      `paced` (OFClient.get_json calls it). No claim: every walker is single-flight by
      its own lock or loop already. `account_id` names the walk (None: a pass over many
      Creators; logged as walk= on a 429 retry); pages pace on their client's
      account (a client with none: unpaced). Its OF calls count as `walk:<kind>`
      (of_call_counter).
  paced(account_id, call)          (sync, in the walk's worker thread)
      Outside a walk: `call()` as before. Inside: `account_id`'s pacer, then `call()`; on
      OF's 429 it waits what OF asks and sends the SAME request once more. A second 429
      raises as before: a failed page, never an empty one.
  paced(account_id, call, proxy_key)
      OFClient.get_json passes its client's exit resolver (OFClient.pace_key). A page of a walk
      whose kind is in _PROXY_PACED_KINDS (the ledger's `transactions`) resolves it (once a page)
      and takes the Creator's slot AND that exit's, both free, both stamped at once; any other
      walk's, the Creator's only (never resolved).
  absorb_429(account_id, call, *, send_deadline=None)
      OF's 429 closes the Creator's gate. After a cooldown, one probe goes:
      sends first, then reads, then walk pages, oldest first within each class.
      A successful probe opens the gate and spaces out queued requests.
      Reads have READ_BUDGET_S to wait. Sends pass an absolute dispatch deadline.
  upstream(exc) / allow_s(text) / asked_wait(header, allow)
      The one reader of OF's answer behind an exception: (status, body, Retry-After header);
      "Please allow N seconds" as N, uncapped; OF's asked wait (the header first, else the
      text), uncapped. retry_after (this module's capped wait) and the purchases poll's
      Backoff ladder read through them.
  note_user(account_id) / last_user_at(account_id) / user_active(account_id)
      A person's request for the Creator (server._lane_entered: a non-background lane entry
      made from a real request; the Promotions page) / its monotonic time (vault_collect) /
      one in the last USER_WINDOW_S (10 s):
      link_prewarm.prewarm_all skips that Creator this pass and walks it the next; no waiting.
      No walk holds the lock the Growth page's reads take (of_tracking_api._LOCKS) across an
      OF call or a pause.

The pacer is ONE per Creator, shared by every job: a background GET leaves PAGE_GAP_S
(+ 0..JITTER_S) after the Creator's previous one, whichever walk sent it, so two jobs'
1 s loops cannot burst together. Pages only: CDN, media and /img fetches never come here.
User reads are never paced; only absorb_429's gate holds them. A walk's page never leaves while its
Creator's gate is cooling or probing. A walk can close the gate and claim a probe.
Stdlib only plus of_call_counter (a leaf: of_client
imports it).

Ledger walk pages are paced per proxy exit too (AE 2026-11-08, measured: the ledger's 429s
followed the proxy IP, not the Creator; 16 Creators on ~3 proxies, 4 walks at once). The slot
is keyed on the exit of the endpoint the client was BUILT with (OFClient.pace_key,
proxies.egress_identity against the registry read per page: the verified exit IP, else host:port;
no credentials; "direct" for a direct client), never a fresh account->proxy lookup: after an
ADR-0030 move an outstanding client keeps its old exit's slot, the next client takes the new
one's; a probe verifying an endpoint's IP later moves both clients on it to that IP's slot. Never rotated on a 429. By walk kind, not URL: the
`transactions` walk's every page (its ledger pages and the purchases-feed read after them);
the disputes poll (`chargebacks`, its own walk, a page or two a full walk) and every other walk
stay per Creator.

Limits, as built (kept on purpose):
  * Not fair between jobs: every waiter wakes and asks again, the first to ask gets the slot;
    a long walk can delay another job's pages on the same Creator, never break them.
  * Walks take no relay lane: they call the OF client directly in a worker thread
    (link_metrics' asyncio.to_thread(walk, client, ...), promo_reactivate, the roster /
    ledger / auto-exclude crawls, a plugin's background loop), so server.py's "<= 2 background per Creator" lane
    cap does not bound them, and a paced page sleeps IN that thread (time.sleep in `paced`).
    Threads asleep at once on a 50-Creator box, counted from the code (inferred): link prewarm 1
    (serial pass); Growth refresh / Details re-walk / list adds <= 1 per Creator (walk lock),
    only Creators whose Growth page was opened; ledger supervisor 4 (refresh 4, then backfill 2);
    roster crawl <= 8 (inside automation runs: run_slot.auto_runs(50) = 6 + 2 operator);
    promo_reactivate shares those 8 slots; auto-exclude <= 1 per Creator with a big list due
    (single-flight per Creator, no global cap); each walking plugin loop
    (relay_hooks.background_loops) 1 (one sequential pass). Worst case
    ~1 + 50 + 4 + 8 + 50 = 113, plus 1 per such loop, of the 378-thread default executor
    (server._EXECUTOR_THREADS).
  * Only reads are paced: OFClient.get_json is the one seam wrapped. Writes inside a walk
    (link_metrics.sync_lists' add-to-list, audiences' batch list adds) are not, by the owner's
    rule that writes are never throttled; sync_lists keeps its own 0.4 s gap between adds.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import logging
import random
import re
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable

import of_call_counter

log = logging.getLogger("of-relay.of_pacing")

PAGE_GAP_S = 1.0  # OF: "Please allow 1 seconds"
JITTER_S = 0.3
RETRY_DEFAULT_S = 1.0  # a 429 whose text names no wait
RETRY_MAX_S = 10.0
COOLDOWNS_S = (3.0, 5.0, 8.0, 13.0, 21.0, 34.0)  # owner: the gate's cooldown per 429 in a row
READ_BUDGET_S = 45.0
SEND_BUDGET_S = 55.0  # leaves room for the OF POST before Cloudflare's origin deadline
MAX_READ_WAITERS = 16
RETRY_HEADER_MAX_S = 120.0
POLL_S = 0.25
USER_WINDOW_S = 10.0

_ALLOW = re.compile(r"allow\s+(\d+(?:\.\d+)?)\s*sec", re.I)
_PROXY_PACED_KINDS = frozenset({"transactions"})   # walks whose pages also take their exit's slot


@dataclass
class _Walk:
    account_id: str | None
    kind: str


_WALK: ContextVar[_Walk | None] = ContextVar("of_pacing_walk", default=None)
_lock = threading.Lock()
_next_at: dict[str, float] = {}
_last_user: dict[str, float] = {}


@dataclass
class _Gate:
    closed: bool = False
    cool_until: float = 0.0
    step: int = 0
    epoch: int = 0  # bumped on every close and open: a 429 counts only for its own epoch
    probing: bool = False
    next_at: float = 0.0
    closed_at: float = 0.0
    queue: set[tuple[int, int]] = field(default_factory=set)
    last_429: BaseException | None = None


_gates: dict[str, _Gate] = {}
_gates_lock = threading.Lock()
_tickets = itertools.count()


def note_user(account_id: Any) -> None:
    if account_id:
        _last_user[str(account_id)] = time.monotonic()


def last_user_at(account_id: Any) -> float | None:
    return _last_user.get(str(account_id))


def user_active(account_id: Any, now: float | None = None) -> bool:
    t = _last_user.get(str(account_id))
    return t is not None and (time.monotonic() if now is None else now) - t < USER_WINDOW_S


def allow_s(text: str | None) -> float | None:
    m = _ALLOW.search(text or "")
    return max(float(m.group(1)), 0.0) if m else None


def asked_wait(header: str | None, allow: float | None) -> float | None:
    if header is not None:
        try:
            v = float(str(header).strip())
            if v >= 0:
                return v
        except ValueError:
            try:
                v = parsedate_to_datetime(header).timestamp() - time.time()
                if v > 0:
                    return v
            except (ValueError, TypeError, OverflowError, OSError):
                pass
    return allow


def parse_allow(text: str | None) -> float:
    a = allow_s(text)
    return min(RETRY_DEFAULT_S if a is None else a, RETRY_MAX_S)


def upstream(exc: BaseException) -> tuple[int | str | None, str, str | None]:
    # Status is OF's int or one of _proxy's string codes (proxy_unreachable, timeout, network, refused_by_relay, session_retired, signed_pool_busy): isinstance-check before comparing.
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return detail.get("upstream_status"), str(detail.get("upstream_body") or ""), None
    resp = getattr(exc, "response", None)
    header = (getattr(resp, "headers", None) or {}).get("Retry-After")  # curl_cffi headers: case-insensitive
    return getattr(resp, "status_code", None), getattr(resp, "text", "") or "", header


def retry_after(exc: BaseException) -> float | None:
    status, body, header = upstream(exc)
    if status != 429:
        return None
    wait = asked_wait(header, None)
    return parse_allow(body) if wait is None else min(wait, RETRY_HEADER_MAX_S)


def _turn(*keys: str) -> float:
    # Stamped on departure, not booked ahead (a late sender never lets the next leave right behind it); check and stamp under one lock.
    with _lock:
        now = time.monotonic()
        at = max(_next_at.get(k, 0.0) for k in keys)
        if at > now:
            return at - now
        nxt = now + PAGE_GAP_S + random.uniform(0.0, JITTER_S)
        for k in keys:
            _next_at[k] = nxt
        return 0.0


def exit_label(exit_: str | None) -> str:
    # Never an IP, host, port or credential.
    if not exit_ or exit_ == "direct":
        return exit_ or "-"
    return "p-" + hashlib.sha1(exit_.encode()).hexdigest()[:8]


def paced(account_id: Any, call: Callable[[], Any], proxy_key: Callable[[], str] | None = None) -> Any:
    w = _WALK.get()
    if w is None:
        return call()
    if account_id is None:
        return call()
    aid = str(account_id)
    exit_ = proxy_key() if proxy_key is not None and w.kind in _PROXY_PACED_KINDS else None
    keys = (aid,) if exit_ is None else (aid, f"proxy {exit_}")
    try:
        return _walk_attempt(aid, keys, call)
    except Exception as e:
        wait = retry_after(e)
        if wait is None:
            raise
    # walk= after kind=: proxy-health's summarize.py matches "account=... kind=transactions".
    log.info("bg_walk_429_retry account=%s kind=%s walk=%s proxy=%s wait_s=%.1f", aid, w.kind,
             w.account_id or "-", exit_label(exit_), wait)
    time.sleep(wait)
    return _walk_attempt(aid, keys, call)


def _walk_attempt(aid: str, keys: tuple[str, ...], call: Callable[[], Any]) -> Any:
    with _gates_lock:
        g = _gates.setdefault(aid, _Gate())
    me = (2, next(_tickets))
    try:
        while True:
            with _gates_lock:
                action, delay = _admit(g, me, time.monotonic(), keys)
                epoch = g.epoch
            if action != "wait":
                return _gate_call(aid, g, call, action == "probe", epoch, time.monotonic)
            time.sleep(delay)
    finally:
        with _gates_lock:
            g.queue.discard(me)


def _close(aid: str, g: _Gate, e: BaseException, now: float) -> None:
    if g.closed and now - g.cool_until > COOLDOWNS_S[-1]:
        g.step = 0  # nobody probed for a whole top cooldown: start the ladder again
    cool = max(COOLDOWNS_S[min(g.step, len(COOLDOWNS_S) - 1)], retry_after(e) or 0.0)
    if not g.closed:
        g.closed_at = now
    g.closed, g.probing, g.last_429 = True, False, e
    g.cool_until = now + cool
    g.step += 1
    g.epoch += 1
    log.info("of_gate_closed account=%s step=%d cooldown_s=%.0f waiting=%d", aid, g.step, cool, len(g.queue))


def _open(aid: str, g: _Gate, now: float) -> None:
    log.info("of_gate_opened account=%s step=%d closed_s=%.1f waiting=%d", aid, g.step, now - g.closed_at,
             len(g.queue))
    g.closed = g.probing = False
    g.epoch += 1
    g.next_at = now + PAGE_GAP_S + random.uniform(0.0, JITTER_S)
    if not g.queue:
        g.step = 0


def _admit(
    g: _Gate, me: tuple[int, int], now: float, pace_keys: tuple[str, ...] = (),
) -> tuple[str, float]:
    queued = g.closed or bool(g.queue)
    if queued:
        g.queue.add(me)
        if g.closed and g.cool_until > now:
            return "wait", g.cool_until - now
        if g.probing or min(g.queue) != me:
            return "wait", POLL_S if g.closed else max(g.next_at - now, POLL_S)
    if not g.closed and (queued or pace_keys) and g.next_at > now:
        return "wait", g.next_at - now
    if pace_keys and (delay := _turn(*pace_keys)):
        return "wait", delay
    g.queue.discard(me)
    if g.closed:
        g.probing = True
        return "probe", 0.0
    if queued:
        g.next_at = now + PAGE_GAP_S + random.uniform(0.0, JITTER_S)
        if not g.queue:
            g.step = 0
    return "go", 0.0


def _gate_call(
    aid: str, g: _Gate, call: Callable[[], Any], probe: bool, epoch: int, clock: Callable[[], float],
) -> Any:
    try:
        out = call()
    except Exception as e:
        if retry_after(e) is not None:
            with _gates_lock:
                now = clock()
                if epoch == g.epoch:
                    _close(aid, g, e, now)
                elif g.closed and not g.probing:
                    g.cool_until = max(g.cool_until, now + (retry_after(e) or 0.0))
        raise
    else:
        if probe:
            with _gates_lock:
                _open(aid, g, clock())
        return out
    finally:
        if probe:
            with _gates_lock:
                if epoch == g.epoch:
                    g.probing = False


class SendDispatchExpired(Exception):
    pass


def absorb_429(account_id: Any, call: Callable[[], Any], *,
               sleep: Callable[[float], Any] = time.sleep, clock: Callable[[], float] = time.monotonic,
               send_deadline: float | None = None) -> Any:
    if account_id is None:
        return call()
    aid = str(account_id)
    with _gates_lock:
        g = _gates.setdefault(aid, _Gate())
    send = send_deadline is not None
    me = (0 if send else 1, next(_tickets))
    t0 = clock()
    deadline = send_deadline if send_deadline is not None else t0 + READ_BUDGET_S
    own: BaseException | None = None
    try:
        while True:
            with _gates_lock:
                now = clock()
                last = g.last_429 if g.closed or g.queue else None
                full = (not send and me not in g.queue and
                        sum(priority == 1 for priority, _ in g.queue) >= MAX_READ_WAITERS)
                if full or (now >= deadline and (send or own is not None or last is not None)):
                    break
                action, delay = _admit(g, me, now)
                epoch = g.epoch
            if action == "wait":
                if now + delay >= deadline:
                    break
                sleep(delay)
                continue
            try:
                return _gate_call(aid, g, call, action == "probe", epoch, clock)
            except SendDispatchExpired:
                now = clock()
                break
            except Exception as e:
                if retry_after(e) is None:
                    raise
                own = e
                with _gates_lock:
                    now = clock()
                    wait = max(g.cool_until - now, 0.0)
                log.info("request_429_retry account=%s wait_s=%.1f waited_s=%.1f", aid, wait, now - t0)
        log.info("request_429_gave_up account=%s waited_s=%.1f send=%d", aid, now - t0, send)
        if own is not None:
            raise own from None
        if last is not None:
            raise copy.copy(last) from None
        raise SendDispatchExpired() from None
    finally:
        with _gates_lock:
            g.queue.discard(me)


async def walk(account_id: Any, kind: str, run: Callable[[], Awaitable[Any]]) -> Any:
    tok = _WALK.set(_Walk(None if account_id is None else str(account_id), kind))
    try:
        with of_call_counter.caller(f"walk:{kind}"):
            return await run()
    finally:
        _WALK.reset(tok)
