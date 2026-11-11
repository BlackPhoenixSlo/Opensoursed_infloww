"""service/of_pacing.py — background OnlyFans list walks: paced per Creator, one retry on
OF's 429; and the relay's one "a person is on this Creator" signal (the hourly link prewarm
and the vault collector read it).

Why (measured on AE, 18 h to 2026-11-05): OF answered "Too many requests. Please allow 1
seconds" 281 times, every one to a background walk (promotions 121, /users/list 148,
payouts 11), none to a click. The walks paged as fast as OF answered.

  walk(account_id, kind, run, *, retry_429=True, before_call=None)
      Runs `run()` as a background walk: inside it, every OFClient GET goes through
      `paced` (OFClient.get_json calls it). No claim: every walker is single-flight by
      its own lock or loop already. `account_id` names the walk (None: a pass over many
      Creators; logged as walk= on a 429 retry); pages pace on their client's
      account (a client with none: unpaced). Its OF calls count as `walk:<kind>`
      (of_call_counter). `retry_429=False`: `paced` still waits its turn but re-raises
      OF's 429 at once; the caller owns the retry (audience_crawl's Backoff ladder).
      `before_call`, when given, runs in the worker after pacing, before each departure
      (including a retry or bare client). It may raise to refuse a now-expired read.
  paced(account_id, call)          (sync, in the walk's worker thread)
      Outside a walk: `call()` as before. Inside: `account_id`'s pacer, then `call()`; on
      OF's 429 it waits what OF asks and sends the SAME request once more. A second 429
      raises as before: a failed page, never an empty one.
  paced(account_id, call, proxy_key)
      OFClient.get_json passes its client's exit resolver (OFClient.pace_key). A page of a walk
      whose kind is in _PROXY_PACED_KINDS (the ledger's `transactions`) resolves it (once a page)
      and takes the Creator's slot AND that exit's, both free, both stamped at once; any other
      walk's, the Creator's only (never resolved).
  retry_429(account_id, call)      (async)
      The 429 retry alone, for a request a person's page sends itself (`X-Priority:
      background` /users/list name fill, server.py): user-triggered, so never paced. The
      wait is on the loop (no worker thread), but inside the request's background
      admission: it holds the Creator's background lane slot (<= RETRY_MAX_S).
  upstream(exc) / allow_s(text)
      The one reader of OF's answer behind an exception: (status, body, Retry-After header);
      "Please allow N seconds" as N, uncapped. retry_after (this module's capped wait) and
      audience_crawl's Backoff ladder both read through them.
  note_user(account_id) / last_user_at(account_id) / user_active(account_id)
      A person's request for the Creator (server._lane_entered: a non-background lane entry
      made from a real request; the Promotions page) / its monotonic time (vault_collect) /
      one in the last USER_WINDOW_S (10 s):
      link_metrics.prewarm_all skips that Creator this pass and walks it the next; no waiting.
      No walk holds the lock the Growth page's reads take (of_tracking_api._LOCKS) across an
      OF call or a pause.

The pacer is ONE per Creator, shared by every job: a background GET leaves PAGE_GAP_S
(+ 0..JITTER_S) after the Creator's previous one, whichever walk sent it, so two jobs'
1 s loops cannot burst together. Pages only: CDN, media and /img fetches never come here.
User reads never do either: no walk, no pause, no retry. Stdlib only plus of_call_counter (a leaf: of_client
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
    (link_metrics' asyncio.to_thread(walk, client, ...), promo_reactivate, the
    roster / ledger / auto-exclude crawls), so server.py's "<= 2 background per Creator" lane
    cap does not bound them, and a paced page sleeps IN that thread (time.sleep in `paced`).
    Threads asleep at once on a 50-Creator box, counted from the code (inferred): link prewarm 1
    (serial pass); Growth refresh / Details re-walk / list adds <= 1 per Creator (walk lock),
    only Creators whose Growth page was opened; ledger supervisor 4 (refresh 4, then backfill 2);
    roster crawl <= 8 (inside automation runs: run_slot.auto_runs(50) = 6 + 2 operator);
    promo_reactivate shares those 8 slots; auto-exclude <= 1 per Creator with a big list due
    (single-flight per Creator, no global cap); audience crawl <= 1 page thread per Creator
    (one crawler per Creator, its waits on the loop). Worst case
    ~1 + 50 + 4 + 8 + 50 + 50 = 163 of the 378-thread default executor (server._EXECUTOR_THREADS).
  * Only reads are paced: OFClient.get_json is the one seam wrapped. Writes inside a walk
    (link_metrics.sync_lists' add-to-list, audiences' batch list adds) are not, by the owner's
    rule that writes are never throttled; sync_lists keeps its own 0.4 s gap between adds.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import of_call_counter

log = logging.getLogger("of-relay.of_pacing")

PAGE_GAP_S = 1.0          # OF: "Please allow 1 seconds"
JITTER_S = 0.3
RETRY_DEFAULT_S = 1.0     # a 429 whose text names no wait
RETRY_MAX_S = 10.0
USER_WINDOW_S = 10.0      # link_metrics.prewarm_all skips a Creator with a person's read this recent

_ALLOW = re.compile(r"allow\s+(\d+(?:\.\d+)?)\s*sec", re.I)
_PROXY_PACED_KINDS = frozenset({"transactions"})   # walks whose pages also take their exit's slot


@dataclass
class _Walk:
    account_id: str | None
    kind: str
    retry_429: bool = True
    before_call: Callable[[], None] | None = None


_WALK: ContextVar[_Walk | None] = ContextVar("of_pacing_walk", default=None)
_lock = threading.Lock()
_next_at: dict[str, float] = {}       # pace key (a Creator, or "proxy <exit>") -> monotonic time its next
                                      # background GET may leave
_last_user: dict[str, float] = {}     # Creator -> monotonic time of its last user request


def note_user(account_id: Any) -> None:
    if account_id:
        _last_user[str(account_id)] = time.monotonic()


def last_user_at(account_id: Any) -> float | None:
    return _last_user.get(str(account_id))


def user_active(account_id: Any, now: float | None = None) -> bool:
    t = _last_user.get(str(account_id))
    return t is not None and (time.monotonic() if now is None else now) - t < USER_WINDOW_S


def allow_s(text: str | None) -> float | None:
    """OF's "Please allow N seconds" as N (uncapped, >= 0), None when the text names none."""
    m = _ALLOW.search(text or "")
    return max(float(m.group(1)), 0.0) if m else None


def parse_allow(text: str | None) -> float:
    """OF's asked wait ("Please allow N seconds"), RETRY_DEFAULT_S when it names none,
    never above RETRY_MAX_S."""
    a = allow_s(text)
    return min(RETRY_DEFAULT_S if a is None else a, RETRY_MAX_S)


def upstream(exc: BaseException) -> tuple[int | None, str, str | None]:
    """OF's answer behind `exc`: (status, body text, Retry-After header). An OFAPIError's
    `response`, or server._proxy's 502 whose detail carries upstream_status / upstream_body
    (no header there: None). Anything else: (None, "", None)."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return detail.get("upstream_status"), str(detail.get("upstream_body") or ""), None
    resp = getattr(exc, "response", None)
    header = (getattr(resp, "headers", None) or {}).get("Retry-After")   # curl_cffi headers: case-insensitive
    return getattr(resp, "status_code", None), getattr(resp, "text", "") or "", header


def retry_after(exc: BaseException) -> float | None:
    """The wait OF asks for when `exc` is its 429 (see `upstream`), capped (parse_allow),
    else None."""
    status, body, _ = upstream(exc)
    return parse_allow(body) if status == 429 else None


def _turn(*keys: str) -> float:
    """0.0 when every key's next background GET may leave now (the departure is stamped on
    all of them at once: the next one leaves PAGE_GAP_S + jitter after it), else the seconds
    to wait and ask again. Stamped on departure, not booked ahead: a sender that woke late
    never lets the next one leave right behind it; checked and stamped under one lock, so no
    key is held while another waits."""
    with _lock:
        now = time.monotonic()
        at = max(_next_at.get(k, 0.0) for k in keys)
        if at > now:
            return at - now
        nxt = now + PAGE_GAP_S + random.uniform(0.0, JITTER_S)
        for k in keys:
            _next_at[k] = nxt
        return 0.0


def _wait_turn(*keys: str) -> None:
    while (d := _turn(*keys)) > 0:
        time.sleep(d)


def paced(account_id: Any, call: Callable[[], Any], proxy_key: Callable[[], str] | None = None) -> Any:
    w = _WALK.get()
    if w is None:
        return call()
    if account_id is None:   # a bare client has no Creator to pace on, but still needs admission
        if w.before_call is not None:
            w.before_call()
        return call()
    aid = str(account_id)
    exit_ = proxy_key() if proxy_key is not None and w.kind in _PROXY_PACED_KINDS else None
    keys = (aid,) if exit_ is None else (aid, f"proxy {exit_}")
    _wait_turn(*keys)
    if w.before_call is not None:
        w.before_call()
    if not w.retry_429:
        return call()
    try:
        return call()
    except Exception as e:
        wait = retry_after(e)
        if wait is None:
            raise
    # Outside the except: OF's second 429 is the page's own error, not one "during handling" the first.
    # walk= after kind=: proxy-health's summarize.py matches "account=... kind=transactions".
    log.info("bg_walk_429_retry account=%s kind=%s walk=%s proxy=%s wait_s=%.1f", aid, w.kind,
             w.account_id or "-", exit_ or "-", wait)
    time.sleep(wait)
    _wait_turn(*keys)
    if w.before_call is not None:
        w.before_call()
    return call()


async def retry_429(account_id: Any, call: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await call()
    except Exception as e:
        wait = retry_after(e)
        if wait is None:
            raise
    log.info("bg_request_429_retry account=%s wait_s=%.1f", account_id, wait)
    await asyncio.sleep(wait)
    return await call()


async def walk(account_id: Any, kind: str, run: Callable[[], Awaitable[Any]], *,
               retry_429: bool = True, before_call: Callable[[], None] | None = None) -> Any:
    tok = _WALK.set(_Walk(None if account_id is None else str(account_id), kind, retry_429, before_call))
    try:
        with of_call_counter.caller(f"walk:{kind}"):
            return await run()
    finally:
        _WALK.reset(tok)   # the caller's context never sees the walk
