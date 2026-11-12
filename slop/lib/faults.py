"""Break-it-once: named product faults the relay wrapper can inject.

`slop/run <scenario> --break` runs a green baseline, then the same run with the
scenario's FAULT applied. CAUGHT means every check the fault declares in
`targets` went PASS -> FAIL; any other check that changed is reported as noise
and catches nothing. If a targeted check stays green, the mutation is NOT
caught: the invariants are blind to it.

A fault patches a real product function inside the throwaway relay process
(never the repo files). Add one per bug class a scenario claims to catch, and
name in `targets` the exact check names (ctx.check) that must see it.

A client fault (`browser=`) patches the app's code the way the relay's are
patched, in flight: actors/ui.py rewrites the JavaScript `next dev` serves on
its way to Chromium (a Playwright route; `next dev` serves each module
unminified), never the repo files. A run where a rewrite never matched the
served code is INFRA (the pattern went stale), so it cannot read as NOT CAUGHT.

A flow kept in files of its own (`lib/<flow>_faults.py`) brings its faults there:
its `register(Fault)` returns them by name and they join FAULTS below, when the
module is present.
"""
from __future__ import annotations

import importlib
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


def _transcoder_drops_1_in_10() -> None:
    """The WS transcoder silently loses every 10th chat message (persist-path bug class)."""
    import event_transcoder
    real = event_transcoder.transcode
    n = itertools.count(1)

    async def lossy(event):
        if isinstance(event, dict) and "api2_chat_message" in event and next(n) % 10 == 0:
            return None
        return await real(event)

    event_transcoder.transcode = lossy


def _sse_fanout_reorders_within_thread() -> None:
    """SSE fan-out delivers a fan's DM AFTER that fan's next DM: every 5th chat
    frame is held and released behind the same thread's next one (or after 3 s
    if none comes). Nothing is lost and the DB is untouched, so only a per-thread
    ordering check on what the stream delivered can see it (the bug class of a
    fan-out batcher/coalescer that regroups frames)."""
    import asyncio

    import events
    real = events.broadcast
    held: dict[tuple, dict] = {}
    n = itertools.count(1)

    def thread_of(event) -> tuple | None:
        m = event.get("api2_chat_message") if isinstance(event, dict) else None
        if not isinstance(m, dict):
            return None
        return str(event.get("__account_id")), (m.get("fromUser") or {}).get("id")

    def flush(key) -> None:
        if key in held:
            asyncio.ensure_future(real(held.pop(key)))

    async def reordering(event):
        key = thread_of(event)
        if key is None:
            return await real(event)
        if key in held:
            first = held.pop(key)
            delivered = await real(event)
            await real(first)
            return delivered
        if next(n) % 5 == 0:
            held[key] = event
            asyncio.get_running_loop().call_later(3.0, flush, key)
            return 1
        return await real(event)

    events.broadcast = reordering


def _access_log_writer_spin_waits() -> None:
    """The API access-log writer thread spin-waits for its next line: after each
    write it hashes a 1 MiB buffer in a loop until a line is queued (or 1 s), as a
    busy C loop would, instead of blocking in Queue.get(). hashlib releases the GIL,
    so the event loop barely notices and nothing is lost or late; the relay just
    burns about one more core. Only the process CPU check can see it. (Spinning on
    the event loop itself instead slows every request, which piles up sessions and
    sets off the SQLite connection storm: measured, latencies go red too.)"""
    import hashlib
    import time

    import server
    real = server._api_log_write
    buf = b"\0" * (1 << 20)

    def spinning(lines):
        real(lines)
        t = time.monotonic()
        while server._api_log_queue.empty() and time.monotonic() - t < 1.0:
            hashlib.sha256(buf)

    server._api_log_write = spinning  # the writer thread looks it up per line


def _db_pool_unbounded_overflow() -> None:
    """The relay's DB pool as it was before 03-write-storm: 5 kept connections and
    unbounded overflow, so a checkout that finds none free opens a new SQLite
    connection (a thread, a schema parse) instead of waiting for one. Every write
    still lands; under a pile-up (the scenario's 2 s stall) the relay opens 200+
    connections and burns 4-11 cores for seconds. Only the stall check can see it
    reliably (the natural storm comes and goes)."""
    import sys

    from sqlalchemy.pool import AsyncAdaptedQueuePool

    import db.engine  # noqa: F401 — the package re-exports `engine` over the module name
    pool = sys.modules["db.engine"].engine.sync_engine.pool
    if "_queue" in pool._pool.__dict__ or pool.checkedout() or pool.checkedin():
        raise SystemExit("slop: db-pool-unbounded-overflow must be applied before the first DB session")
    pool.__class__ = AsyncAdaptedQueuePool  # QueuePool._do_get: max_overflow=-1 never waits
    pool._pool.maxsize, pool._overflow = 5, -5
    pool._pool.__dict__.pop("_queue", None)  # memoized at maxsize 8 by checkedout() above


def _write_telemetry_misses_1_in_50_dms() -> None:
    """The write-path telemetry line under-reports: every 50th inbound DM frame
    is not counted (an ingest counter on the wrong branch). The DM itself is
    persisted, transcoded and fanned out as ever, so only the check that sums
    the telemetry lines against what was injected can see it."""
    from db import write_telemetry
    real = write_telemetry.frame
    n = itertools.count(1)

    def undercount(account_id, event_type, event):
        if event_type == "api2_chat_message" and next(n) % 50 == 0:
            return None
        return real(account_id, event_type, event)

    write_telemetry.frame = undercount  # events.handle_event looks it up per frame


def _of_writer_per_op_txns() -> None:
    """The OF-cache writer never starts (db/of_writer.py as if batching were off):
    every DM's event_inbox row, its transcode and every mark-read is written through
    in a transaction of its own, as before the writer. Nothing is lost and every
    row is right, so only the write-transaction checks can see it."""
    from db import of_writer
    of_writer.start = lambda: None


def _of_writer_holds_batches_3s() -> None:
    """The OF-cache writer waits 3 s before committing each batch (bug class: a
    timer / fill-the-batch writer instead of flushing as soon as work exists).
    Every row still lands, so only a crash shows it: the loss window grows from
    the in-flight batch to seconds of DMs."""
    import asyncio

    from db import of_writer
    real = of_writer._flush

    async def held(batch):
        await asyncio.sleep(3)
        return await real(batch)

    of_writer._flush = held


# Fleet faults (`--shards=N`, lib/edge.py). They break the fleet's wiring, not a
# function inside one relay, so they have no in-relay `apply`: `stack(fleet)` runs
# in the harness before the stack starts and changes what lib/edge.py hands the
# processes (env, the Caddyfile it renders) or flags the scenario.

def _fleet_whois_off(fleet) -> None:
    """Every shard but the front runs without FLEET_SECRET, so its relay never
    mounts GET /auth/fleet/whois (404): the front cannot find a login held on a
    peer (bug class: a shard deployed without the fleet secret, or a renamed
    route). The DM path, the edge and every relay's own sign-in are untouched."""
    for i in range(1, fleet.stack.shards):
        fleet.stack.relay_env[i].pop("FLEET_SECRET", None)
        fleet.stack.relay_env[i]["FLEET_SECRET"] = ""


def _fleet_host_swap(fleet) -> None:
    """The edge sends s04's host to s05's relay and app and s05's to s04's (bug
    class: a fleet map / Caddyfile edit that crosses two shards' ports). Only
    the Caddyfile changes; every process keeps its true env and FLEET_PEERS."""
    fleet.swap_edge("s04", "s05")


def _litestream_paused(fleet) -> None:
    """Litestream on the replicated shard stops shipping (SIGSTOP) from the second
    load stage until the replica is checked (bug class: a wedged or crashed
    replicator). The relay, its DB and every request path are untouched."""
    fleet.flags.add("litestream-paused")


def _fence_off(fleet) -> None:
    """The epoch fence is off on the dead box: the oi-epoch box A runs (its boot gate
    and its watch unit, both from the copy fleet.py installs in /opt/oi/bin) has
    `is_stale()` answering False, as if the check were never there (the mutant
    16-failover-build's --break uses). Box B, the bucket and the restore are
    untouched. lib/box.py installs that copy on box A; the repo file is never edited."""
    fleet.flags.add("fence-off")


def _restore_stale_point(fleet) -> None:
    """The failover restores an old point instead of the latest: oi-restore gets a
    time 10 s before the kill (bug class: a stale generation / wrong lineage picked,
    a lagging replica). The fence, the edge repoint and the relays are untouched."""
    fleet.flags.add("restore-stale-point")


def _assistant_edit_skips_second_account() -> None:
    """Do-mode's bulk edit (spec D11, service/assistant_edit.apply_one) applies the change on the focused model
    only: every rule on another account answers ok with no diffs, so the results card still reads green (bug
    class: a scope "all" plan whose apply silently drops the other models)."""
    import assistant_edit

    orig = assistant_edit.apply_one

    async def apply_one(rule_id, version, changes, *, home, allowed):
        async with assistant_edit.get_session() as s:
            rule = await s.get(assistant_edit.AutomationRule, rule_id)
            acct = rule.account_id if rule is not None else home
        if acct != home:
            return {"id": rule_id, "ok": True, "diffs": []}
        return await orig(rule_id, version, changes, home=home, allowed=allowed)

    assistant_edit.apply_one = apply_one


def _chatter_access_ignored() -> None:
    """A chatter's per-Creator access (the Employee setup's account list,
    chatter_account_access) is ignored: every chatter sees all of its Agency's
    Creators. The Agency boundary holds (an owner's rows never widen another
    owner's), so only a check for an unassigned Creator of the chatter's OWN
    Agency can see it (bug class: a dropped or inverted allowlist filter)."""
    import chatters

    chatters._filter_owner_accounts = lambda pairs, restrictions: {aid for _uid, aid in pairs}


def _chatter_identity_cache_stale() -> None:
    """The chatter identity cache (service/chatter_identity_cache.py) with
    invalidation and TTL disabled: the bug class is any write site that misses the
    invalidation. A Chatter Access restriction leaves the chatter's cached identity
    in place, so the chatter keeps a Creator taken away from it (the TTL is pinned
    so the run does not depend on when the entry was loaded). Only the own-Agency
    isolation check's restriction probe (its direct read) can see it."""
    import chatter_identity_cache

    assert hasattr(chatter_identity_cache, "invalidate") and hasattr(chatter_identity_cache, "TTL_S")
    chatter_identity_cache.invalidate = lambda: None
    chatter_identity_cache.TTL_S = float("inf")


def _reports_ignore_of_earnings() -> None:
    """The reports read the ledger alone, as before 2026-10-25: OnlyFans' own
    daily earnings (of_earnings_daily) are stored but never read, so a Creator's
    days before it was connected (or that the ledger missed) count $0 and a
    window with unknown days still gets a growth %. The job and the ledger are
    untouched: only the checks that compare the reports with OF's Statistics see it."""
    import of_stats_daily

    async def ledger_only(account_ids, start, end, *, now=None):
        return {}, None

    of_stats_daily.earnings_window = ledger_only


def _of_zero_erases_db_sale() -> None:
    """OF's day replaces the ledger's, as shipped in f96535be0: for every (Creator,
    UTC day) OF's figure is stored for, each category reads OF's net in place of
    the ledger's, so OF's $0 (or a chargeback day's negative) takes away a sale the
    ledger holds. The job, its parser and the ledger are the product's own: only
    `stats._of_top_ups` (max(OF, ledger)) is swapped for OF - ledger, unfloored."""
    import of_stats_daily
    import stats
    import tx_rollup
    from sqlalchemy import text

    async def of_replaces(s, of_cells, dims):
        if not of_cells:
            return []
        params = tx_rollup.Binds()
        keys = ", ".join((*dims, "category"))
        sql = (f"SELECT {keys}, SUM(o_gross - l_gross) AS gross_cents, SUM(o_net - l_net) AS net_cents, "
               "SUM(o_sales - l_sales) AS sales, SUM((o_gross - l_gross) - (o_net - l_net)) AS fee_cents "
               f"FROM ({stats._of_top_up_rows(params, of_cells)}) GROUP BY {keys}")
        return [{**{d: getattr(r, d) for d in dims}, "kind": of_stats_daily.EARNINGS_KIND[r.category],
                 "gross_cents": r.gross_cents, "net_cents": r.net_cents, "net_missing": 0,
                 "net_or_80_cents": r.net_cents, "sales": r.sales, "fee_cents": r.fee_cents, "vat_cents": 0}
                for r in (await s.execute(text(sql), params)).all()]

    stats._of_top_ups = of_replaces


def _health_lane_4_core() -> None:
    """The /setup probe's ceiling (admission.HEALTH_PROBE) back at its 4-core-era 4.
    Set before any loop builds the lane's semaphore (the lane reads `cap` then), so
    the whole run probes 4 Creators at a time: the slow ones behind a dead proxy
    hold every slot and healthy Creators queue past the route's budget."""
    import admission
    admission.HEALTH_PROBE.cap = 4


def _otp_code_never_consumed() -> None:
    """The served Browserbase login never reads its pending 2FA code: POST
    /admin/login/remote/{id}/otp still answers 200 and fills the job's slot,
    but the job's thread never types it into OnlyFans (bug class: a request
    thread and a worker thread that never meet)."""
    import remote_login

    remote_login.RemoteLoginJob.take_otp = lambda self: None


def _challenge_counts_hidden_frames() -> None:
    """The served Browserbase login's challenge check as it was before
    2026-10-25: any captcha frame URL on the page counts, on screen or not, and
    so does a hidden Cloudflare element (bug class: a hidden reCAPTCHA frame
    reported as a verification check for the human to solve)."""
    import remote_login

    def detect_any_frame(page) -> bool:
        try:
            if page.evaluate(
                """() => {
                    const t = (document.body && document.body.innerText || '').toLowerCase();
                    if (t.includes('just a moment') || t.includes('verify you are human')
                        || t.includes('checking your browser')) return true;
                    return !!document.querySelector(
                        '#challenge-running, #challenge-stage, #challenge-form, .cf-turnstile');
                }"""
            ):
                return True
        except Exception:  # noqa: BLE001
            pass
        needles = ("turnstile", "recaptcha", "hcaptcha", "geetest", "challenges.cloudflare")
        try:
            return any(any(n in (f.url or "").lower() for n in needles) for f in page.frames)
        except Exception:  # noqa: BLE001
            return False

    remote_login._detect_challenge = detect_any_frame


def _runtime_switch_env_bypass() -> None:
    """W7's kill switch reads the env var directly, as before Settings > System
    could set it: the override saved from the UI never reaches the consumer."""
    import os

    import webhook_dispatch

    def env_only() -> bool:
        return os.environ.get("W7_WEBHOOK_DISPATCH_DISABLED", "").strip().lower() in ("1", "true", "yes", "on")

    webhook_dispatch._global_kill_switch = env_only


def _applied_drops_hide_trial_popup() -> None:
    """The Applied settings read never carries Preferences' "Disable free trial popup": the
    saved switch never reaches the shell, so the expired-trial nag keeps showing."""
    import settings_api
    real = settings_api._applied_in

    async def dropped(s, ctx):
        out = await real(s, ctx)
        out["preferences"]["hide_trial_popup"] = False
        return out

    settings_api._applied_in = dropped


# The app's notification clicks before notificationLink.ts: a left click on a
# link opens a browser tab of its own (the toast's named `infloww-rea-<path>`
# target, the bell rows' _blank) instead of the Fan tab in Messages Pro, and the
# OS notification opened a window that is not Messages Pro's. Capture phase on
# the window runs before React's root listener, so the app's handler never sees
# the click; window.open never finds the Messages Pro window, so the OS
# notification's link opens another.
_NOTIF_CLICK_OPENS_BROWSER_TAB = """window.addEventListener("click", (e) => {  // a popup keeps its window, not its about:blank document
  const a = e.target instanceof Element && e.target.closest('a[href^="/messages-pro/"]');
  if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  if (!a.matches('a.animate-toast-in, a[href*="fanTab="]')) return;
  a.target = "infloww-rea-" + new URL(a.href).pathname;
  e.stopPropagation();
}, true);
(() => { const open = window.open;
  window.open = function (url, name, features) {
    if (name !== "messages-pro") return open.call(this, url, name, features);
    if (!url) return null;  // the open Messages Pro window is never found...
    // ...a link opens a new one, named so that no later open (from any page) finds it again
    return open.call(this, url, "slop-not-messages-pro-" + Math.random().toString(36).slice(2), features); }; })();"""
# ...and the desktop app before desktop/lib/window-open.js: a Messages Pro link
# opened as a tab, and the native notification's click, never reach the open
# Messages Pro window (a new window; the main window loads the link). Run by the
# Electron wrapper (actors/notif_click) before desktop/main.js loads.
_NOTIF_CLICK_DESKTOP_IGNORES_MESSAGES_PRO = """const Module = require("module");
const load = Module._load;
Module._load = function (request, ...rest) {
  const m = load.call(this, request, ...rest);
  return /(^|[\\\\/])window-open(\\.js)?$/.test(request) ? { ...m, openInMessagesProWindow: () => false } : m;
};"""


def _relay_cache_no_single_flight() -> None:
    """relay_cache's per-key single-flight off: each miss gets a lock of its own, so
    concurrent misses on one Creator's cold key each read OnlyFans (bug class: a cold
    burst of one Creator's read stampedes OF; Chrome's per-URL cache lock used to
    serialize such a burst before the app's no-store)."""
    import asyncio

    import relay_cache

    async def own_lock(_key):
        return asyncio.Lock()

    relay_cache._get_or_make_lock = own_lock


def _interactive_reads_full_proxy_retry() -> None:
    """The fail-fast read policy reverted (as before the fail-fast interactive reads): a read
    someone waits on retries a dead proxy 5 times with 0.4-3.2 s pauses, as background
    work does (bug class: a person's Fan List / bell / thread waits ~7 s for a 502).
    Counting is left as it is (interactive-failures-counted covers that)."""
    import of_client
    of_client.INTERACTIVE_RETRY = of_client.FULL_RETRY._replace(counts=of_client.INTERACTIVE_RETRY.counts)


def _interactive_failures_counted() -> None:
    """An interactive read's final proxy failure counts toward proxy_health's DOWN_AFTER
    again (as before the proxy failover's review): it gives up inside ~1 s, so three of
    them land inside one CONNECT-403 blip (bug class: a blip that self-heals marks the
    proxy bad, badges its Creators and keeps new logins off it)."""
    import of_client
    of_client.INTERACTIVE_RETRY = of_client.INTERACTIVE_RETRY._replace(counts=True)


def _relay_cache_failure_not_shared() -> None:
    """relay_cache's single-flight on success only (as before the fail-fast interactive reads):
    nothing is kept of a failed fetch, so each caller queued on the key's lock goes
    upstream again after it, one after another (bug class: N readers of a Creator behind
    a dead proxy wait N failures in a row)."""
    import relay_cache

    class _Forgets(dict):
        def __setitem__(self, _k, _v) -> None:
            pass

    relay_cache._failed = _Forgets()

def _otp_state_not_session_dead() -> None:
    """The classifier's code-101 branch reverted (as before fix/otp-state-session-health):
    OF's 2FA demand is not a dead session, so nothing flags, notifies or pauses the account."""
    import account_health
    account_health._wants_otp = lambda exc: False


def _session_dead_claim_not_atomic() -> None:
    """The healthy -> dead flip as it was before fix/otp-state-session-health: read the
    row, then write it, so callers that meet OF's rejection at the same moment each read
    "healthy" and each notify (bug class: check-then-act across an await)."""
    from datetime import datetime

    from sqlalchemy import select

    import account_health
    from account_health import AccountHealth, _announce, get_session

    async def mark_session_dead(account_id: str, reason: str) -> bool:
        now = datetime.utcnow()
        async with get_session() as s:
            row = (await s.execute(select(AccountHealth).where(AccountHealth.account_id == account_id)
                                   )).scalar_one_or_none()
            newly = row is None or row.session_dead_at is None
            if row is None:
                s.add(AccountHealth(account_id=account_id, session_dead_at=now, session_dead_reason=reason))
            elif newly:
                row.session_dead_at, row.session_dead_reason, row.last_probe_at = now, reason, None
            if newly:
                _announce(s, "session_dead", account_id, dead=True, reason=reason)
        if newly:
            from notifications_api import notify_session_dead
            await notify_session_dead(account_id, reason, now)
        return newly

    account_health.mark_session_dead = mark_session_dead


def _retired_read_not_rerun() -> None:
    """server._proxy as it was after 0b87e9621 (evict retires a client's signed handles),
    before fix/retired-read-retry: a call whose client was evicted under it answers 502
    with upstream 500 "signed session retired" (no re-run on the current client), and a
    dead-session answer evicts whichever client the pool holds, so a read still on a
    replaced client retires the fresh one (bug class: a shared handle closed under
    concurrent users)."""
    import client_pool
    import server

    class _NeverRaised(Exception):
        pass

    server.OFSessionRetired = _NeverRaised  # _proxy's except clauses read the name per raise
    real = client_pool.evict
    client_pool.evict = lambda account_id=None, *, only=None: real(account_id)


# The Dashboard's Total earnings chained behind OnlyFans' live reads (bug class: a figure the
# ledger answers in ~70 ms made to wait on per-Creator OF reads through the proxies): the
# revenue read's answer is held until no /api/of/ fetch is in flight, after at least one began.
_DASHBOARD_TOTAL_WAITS_OF_READS = """(() => {
  const real = window.fetch; let inflight = 0, seen = 0;
  // Until the page's OF reads have started and all ended (20 s at most, so a page with none cannot hang).
  const quiet = () => new Promise((ok) => { const t0 = Date.now();
    const t = () => ((seen > 0 && inflight === 0) || Date.now() - t0 > 20000) ? ok() : setTimeout(t, 50); t(); });
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    if (url.includes('/api/of/')) {
      inflight++; seen++;
      const p = real.apply(this, arguments);
      p.then(() => inflight--, () => inflight--);
      return p;
    }
    if (url.includes('/admin/stats/revenue')) return real.apply(this, arguments).then(async (r) => { await quiet(); return r; });
    return real.apply(this, arguments);
  };
})();"""


# app/components/providers.tsx: the React Query snapshot as before 2026-10-28, without the Dashboard's revenue read
# and the Applied settings (`applied-settings`, `dashboard/revenue-by-kind`): every write to the snapshot store drops
# them, so a return visit cuts its days and reads its Total over the network again.
_DASHBOARD_TOTAL_NOT_SAVED = """(() => {
  const put = IDBObjectStore.prototype.put;
  const fixed = (k) => Array.isArray(k) && (k[0] === 'applied-settings' || (k[0] === 'dashboard' && k[1] === 'revenue-by-kind'));
  IDBObjectStore.prototype.put = function (value, key) {
    if (this.name === 'snapshot' && typeof value === 'string') {
      try {
        const c = JSON.parse(value), qs = c && c.clientState && c.clientState.queries;
        if (Array.isArray(qs)) { c.clientState.queries = qs.filter((q) => !fixed(q.queryKey)); value = JSON.stringify(c); }
      } catch (e) { /* not the snapshot's JSON: written as is */ }
    }
    return put.call(this, value, key);
  };
})();"""

# app/components/stats/PerModelKpiGrid.tsx: the Per-model cards blind to which Creators have a session, as before
# 2026-10-28. `GET /admin/accounts` reaches the page as a 503 (the request itself still goes out and answers), so the
# cards take their failed-list path and send every Creator's OnlyFans reads, the session-less one's included (404
# Unknown account_id), with no "Not connected" label. The Dashboard's screen bundle (app/lib/screenBundle.ts) carries
# the list too: its `accounts` answer is that read's 503 error there.
_DASHBOARD_OFFLINE_CREATOR_READS_OF = """(() => {
  const real = window.fetch;
  const detail = 'slop fault: accounts unavailable';
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    const p = real.apply(this, arguments);
    const path = new URL(url, location.href).pathname;
    if (path === '/admin/screens/dashboard') {
      return p.then(async (r) => {
        if (!r.ok) return r;
        const body = await r.json();
        body.answers = (body.answers || []).filter((a) => a.read !== 'accounts')
          .concat([{ accountId: null, read: 'accounts', status: 503, detail: { detail } }]);
        return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
      });
    }
    if (path !== '/admin/accounts') return p;
    return p.then(() => new Response(JSON.stringify({ detail }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }));
  };
})();"""


# app/components/auth/AuthGate.tsx as before 2026-10-29: nothing drawn while the principal probes run, so the page is
# blank until the app's JS has loaded and /auth/me answered. The server's HTML still carries the boot skeleton (a
# browser rewrite cannot reach the server render), so it is hidden from the first byte: the screen is what the old
# gate's `null` drew. Declared: CSS, not the gate's code.
_BOOT_SKELETON_NOT_DRAWN = """(() => {
  const s = new CSSStyleSheet();
  s.replaceSync('[data-boot-skeleton] { display: none !important; }');
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, s];
})();"""


# The signed-in pages as before 2026-10-29's round two: nothing in place of a page's placeholder bars while its first
# reads run (the old pages drew a spinner, a "Loading…" line or the empty state there instead). Declared: CSS hides every
# `[data-loading]` placeholder from the first byte, not the pages' code.
_PAGE_PLACEHOLDERS_NOT_DRAWN = """(() => {
  const s = new CSSStyleSheet();
  s.replaceSync('[data-loading] { display: none !important; }');
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, s];
})();"""


# The Fan List as before ADR-0003's 2026-10-26 amendment, in the two ways its
# scenario must see: Owe reply laid out last in the chip row, where the "+"
# overflow sat, and a sort button that never looks active (not pressed, not
# blue) whatever order is in force. Layout and attributes only, so React's tree
# and the console are untouched.
_FAN_LIST_OWE_REPLY_LAST_SORT_NEVER_ACTIVE = """(() => {
  const css = '[role=group][aria-label="Fan List filters"] button[title*=" extra \u2014 Owe reply"]'
    + ' { order: 99; }';
  // The sort menu as before 2026-10-27: Newest first, a divider, then "Sort by" over the extras.
  const oldMenu = () => document.querySelectorAll("section[aria-label=Sort]").forEach((m) => {
    const head = m.firstElementChild, first = head && head.nextElementSibling;
    if (!head || head.tagName === "BUTTON" || !first) return;
    const sep = document.createElement("div");
    sep.setAttribute("role", "separator");
    first.after(sep, head);
  });
  const calm = () => { oldMenu(); document.querySelectorAll('button[aria-label^="Sort: "]').forEach((b) => {
    if (b.getAttribute("aria-pressed") === "true") b.setAttribute("aria-pressed", "false");
    if (b.classList.contains("bg-accent")) {
      b.classList.remove("bg-accent", "text-white", "border-accent");
      b.classList.add("text-fg-dim");
    }
  }); };
  const start = () => {
    const s = document.createElement("style");
    s.textContent = css;
    document.head.appendChild(s);
    calm();
    new MutationObserver(calm).observe(document.documentElement,
      { subtree: true, childList: true, attributes: true, attributeFilter: ["class", "aria-pressed"] });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();"""


@dataclass(frozen=True)
class Fault:
    apply: Callable[[], None] | None  # inside the relay (lib/relay.py); None for a harness-side fault
    targets: tuple[str, ...]  # check names that must go PASS -> FAIL under this fault
    stack: Callable[[object], None] | None = None  # harness side, before the stack starts (fleet: lib/edge.Fleet)
    # Client side: (regex, replacement) pairs applied to every JS file under /_next/static/ the
    # browser actor loads (actors/ui.py); each must match at least once in the run, and the
    # matches must land in exactly `browser_files` distinct files (else INFRA: a pattern that
    # also hits another module breaks more than the one function the fault claims).
    browser: tuple[tuple[str, str], ...] = ()
    browser_files: int = 1
    # The same for the app modules lib/app_ts.py loads in node, where a module is one source file
    # (`next dev` bundles a shared one into each page chunk): None = `browser_files`.
    ts_files: int | None = None
    browser_js: str | None = None  # init script in every page actors/ui opens: a bug in the app's browser code
    desktop: str | None = None  # JS the Electron wrapper (actors/notif_click) runs before desktop/main.js


FAULTS: dict[str, Fault] = {
    "transcoder-drops-1-in-10": Fault(_transcoder_drops_1_in_10, (
        "every DM is in its thread (/admin/messages)",
        "unreadMessagesCount == seeded + sent for every burst fan",
    )),
    # slop/run inbox-unread --break --fault=notif-click-opens-browser-tab: every
    # notification click check, browser and desktop (actors/notif_click).
    "notif-click-opens-browser-tab": Fault(None, tuple(
        f"{env} {e} click opens the Fan as a Fan tab in the one Messages Pro window"
        for env, entries in (
            ("browser", ("main-window toast", "Messages Pro toast", "top bar bell row", "/notifications row",
                         "OS notification")),
            ("desktop", ("main-window toast", "Messages Pro toast", "top bar bell row", "native notification")))
        for e in entries
    ), browser_js=_NOTIF_CLICK_OPENS_BROWSER_TAB, desktop=_NOTIF_CLICK_DESKTOP_IGNORES_MESSAGES_PRO),
    # slop/run inbox-unread --break --fault=quick-reply-to-wrong-fan: app/components/NotificationQuickReply.tsx's
    # send hook built for another Fan than its row's (a row's props misrouted, as an index-keyed list did): the
    # reply goes out as the right Creator to the next Fan id. Client side, in flight (actors/ui), never in the repo.
    "quick-reply-to-wrong-fan": Fault(None, (
        "quick reply: OF got exactly one send, as the replied row's Creator to its Fan with the typed text, "
        "none to the other Creator's same Fan; the line is in that thread only (DB)",
    ), browser=((r"accountId,(?:\s|\\n)*fanId,(?:\s|\\n)*hookHandle:(?:\s|\\n)*handle",
                 "accountId, fanId: Number(fanId) + 1, hookHandle: handle"),)),
    "sse-fanout-reorders-within-thread": Fault(_sse_fanout_reorders_within_thread, (
        "per-thread order preserved on every /events stream",
    )),
    # Needs a scenario with CPU_BUDGET_PCT = 80 (the check is named after it):
    # slop/run big-model --break --fault=access-log-writer-spin-waits
    "access-log-writer-spin-waits": Fault(_access_log_writer_spin_waits, (
        "relay process CPU mean <= 80% of one core in every stage",
    )),
    # slop/run big-model --break --fault=db-pool-unbounded-overflow (medium: the stall
    # runs only with stages >= 60 s).
    "db-pool-unbounded-overflow": Fault(_db_pool_unbounded_overflow, (
        "relay absorbs a 2s stall: CPU <= 300% every second and p95 <= 750ms for requests sent in the "
        "30s after (no SQLite connection storm)",
    )),
    # slop/run big-model --break --fault=write-telemetry-misses-1-in-50-dms
    "write-telemetry-misses-1-in-50-dms": Fault(_write_telemetry_misses_1_in_50_dms, (
        "write_telemetry lines: frames and DMs per account == injected",
    )),
    # slop/run big-model-dm-flood --break --fault=of-writer-per-op-txns
    "of-writer-per-op-txns": Fault(_of_writer_per_op_txns, (
        "OF-cache writer: every op committed, and no DM / event_inbox write transaction outside its batches",
        "mark-read: <= 1.05 write transaction per call (its audit row)",
    )),
    # slop/run relay-crash --break (the scenario's FAULT)
    "of-writer-holds-batches-3s": Fault(_of_writer_holds_batches_3s, (
        "crash loses only DMs the relay took < 1000ms before the kill",
    )),
    # slop/run fleet-200 --break (the scenario's FAULT), or --fault=<one of these>
    "fleet-whois-off": Fault(None, (
        "landing login and signup route to the owning / open shard",
    ), stack=_fleet_whois_off),
    "fleet-host-swap": Fault(None, (
        "edge routes each host to its own shard",
        "no cross-shard leakage: each Agency sees exactly its own shard's data at its host",
    ), stack=_fleet_host_swap),
    "litestream-paused": Fault(None, (
        "Litestream replica of the replicated shard restores every DM written while it ran",
    ), stack=_litestream_paused),
    # slop/run box-failover --break (the scenario's FAULT), or --fault=restore-stale-point
    "fence-off": Fault(None, (
        "fence: the returned box runs no relay and writes nothing for the moved shards",
    ), stack=_fence_off),
    # slop/run chatter-crowd --break (the scenario's FAULT)
    "chatter-access-ignored": Fault(_chatter_access_ignored, (
        "no chatter saw an unassigned Creator of its own Agency (stream, inbox, account list, direct reads)",
    )),
    # slop/run chatter-crowd --break --fault=chatter-identity-cache-stale (the restriction probe)
    "chatter-identity-cache-stale": Fault(_chatter_identity_cache_stale, (
        "no chatter saw an unassigned Creator of its own Agency (stream, inbox, account list, direct reads)",
    )),
    # Harness-side, never service/ (lib/relay.py's pool probe; DECLARED: it breaks the harness's
    # reading, not the product). Every pool wait recorded as at least 80 ms, nothing sleeps: the
    # p95 lands in bucket 100 = [75,100), which decision 5's "< 100 ms" holds, so with the half-open
    # gate it is NOT CAUGHT; with `if ms < b` / `wait_p95_ms > gate[...]` reverted it is CAUGHT.
    # slop/run chatter-crowd --break --baseline=<green> --fault=pool-wait-floor-80ms
    "pool-wait-floor-80ms": Fault(None, (
        "DB pool gate (decision 5): 0 spills and pool-wait p95 < 100ms, every shard, every gated stage",
    )),
    # Harness-side (lib/relay.py's /__slop/loop-cpu answers every 4th poll 503): a declared plain
    # fault run, INFRA by design (the stages' pool data is lost: `nodata`), never CAUGHT.
    # slop/run chatter-crowd --break --baseline=<green> --fault=loop-cpu-polls-dropped  (exit 3)
    "loop-cpu-polls-dropped": Fault(None, ()),
    # Scenario-side (chatter-crowd's _direct_read reads ctx.fault): declared plain fault runs, INFRA by
    # design (an unproven isolation probe is undecided, never a pass), never CAUGHT. The first
    # sends only the probe without the chatter's cookie (its controls keep theirs); the second
    # points every target control at a fan of the target Creator with no seeded thread.
    # slop/run chatter-crowd --break --baseline=<green> --fault=iso-probe-cookie-dropped  (exit 3)
    "iso-probe-cookie-dropped": Fault(None, ()),
    # slop/run chatter-crowd --break --baseline=<green> --fault=iso-target-control-unseeded  (exit 3)
    "iso-target-control-unseeded": Fault(None, ()),
    # Harness-side (the scenario passes it to actors/fan_dm.serial, recording only): each fan
    # frame's `due` is stamped 1500 ms early, nothing is sent at another time, so pump lag p95
    # passes 1000 ms with the driver's loop fine: why["pump"], never why["load"].
    # slop/run chatter-crowd --break --baseline=<green> --fault=pump-due-shifted-1500ms
    "pump-due-shifted-1500ms": Fault(None, (
        "offered load met: fan frames on schedule (lag p95 <= 1000ms) and the driver's loop lag "
        "p95 <= 100ms, every gated stage",
    )),
    # slop/run chatter-crowd --layout=one-agency --break --fault=health-lane-4-core
    "health-lane-4-core": Fault(_health_lane_4_core, (
        "owner /setup (GET /health?all_accounts=1, one proxy's Creators dead): 200, exactly the "
        "Agency's Creators, every Creator off the dead proxy ok, only the dead proxy's time out, "
        "every gated stage",
    )),
    # slop/run creator-earnings --break --fault=reports-ignore-of-earnings
    "reports-ignore-of-earnings": Fault(_reports_ignore_of_earnings, (
        "before the history is read, a window with unknown days says so (history_missing_days > 0)",
        "Dashboard and Creator reports totals by kind == max(OF, ledger) per complete day + the ledger (today)",
        "Earnings trends: every day == max(OF, ledger) per category (today: the ledger's)",
        "Creator performance: each Creator's net == max(OF, ledger) per day + today's ledger",
        "growth: the prior window is OF's too, with no unknown day",
        "a window older than OF's kept history says its days are unknown",
    )),
    # slop/run creator-earnings --break (the scenario's FAULT)
    "of-zero-erases-db-sale": Fault(_of_zero_erases_db_sale, (
        "DB sale not erased by OF zero day",
        "Dashboard and Creator reports totals by kind == max(OF, ledger) per complete day + the ledger (today)",
        "Earnings trends: every day == max(OF, ledger) per category (today: the ledger's)",
        "Creator performance: each Creator's net == max(OF, ledger) per day + today's ledger",
    )),
    # slop/run creator-earnings --break --fault=chargebacks-lose-sign
    # The Chargebacks tiles drop their minus (the Dashboard's sum and reportsMath's b - money(r)): they show
    # the reversals as earnings. The relay and every total are right; only the tile check sees it.
    "chargebacks-lose-sign": Fault(None, (
        "chargebacks_tile_negative: Dashboard This month, Creator reports Last 30 days and both at 390px show "
        "Chargebacks == -(the reversed read's net) on the err token",
    ), browser=(
        (r"-rowsOf\(reversed\.data\)", "rowsOf(reversed.data)"),
        (r"b - money\(r\)", "b + money(r)"),
    ), browser_files=2),
    # slop/run scoped-reads --break (the scenario's FAULT)
    "relay-cache-no-single-flight": Fault(_relay_cache_no_single_flight, (
        "cold concurrent burst: OnlyFans saw exactly one call per Creator per read (single-flight)",
    )),
    # slop/run dead-proxy --break (the scenario's FAULT)
    "interactive-reads-full-proxy-retry": Fault(_interactive_reads_full_proxy_retry, (
        "dead proxy: interactive reads answer within budget",
        "dead proxy: each upstream call took the retries its priority gets (interactive 2, background 5), "
        "and the proxy saw exactly those",
    )),
    # slop/run dead-proxy --break --fault=interactive-failures-counted
    "interactive-failures-counted": Fault(_interactive_failures_counted, (
        "dead proxy: a read someone waits on never counts toward bad; the background reads' full-policy "
        "failures do, and no confirm runs inside the blip",
    )),
    # slop/run 2026-10-28-dead-proxy-interactive-reads --scale=medium --users=200 --break --fault=relay-cache-failure-not-shared
    "relay-cache-failure-not-shared": Fault(_relay_cache_failure_not_shared, (
        "dead proxy: interactive reads answer within budget",
    )),
    # slop/run session-health-otp --break (the scenario's FAULT)
    "otp-state-not-session-dead": Fault(_otp_state_not_session_dead, (
        "account_health flags exactly the 2FA Creators, reason otp_required",
        "one session_dead notification per owner per 2FA Creator, opening Browserbase login; "
        "no other owner notified",
        "each affected owner's /events carried the notification and the pause; no other owner's did",
        "a Creator with no automations is flagged by its owner's inbox read alone (via=proxy): "
        "otp_required, one notification",
        "the WS pump met the 2FA demand and parked: per 2FA Creator at most 5 /users/me over >= 25 s "
        "(the pump's 1 + 3 retries, the probe's), all 400, no reconnect, the pump exited within 2 s of "
        "its last /users/me and supervisor passes left it parked",
        "after detection a 2FA Creator runs nothing: no run row, no OF call but the probe's /users/me "
        "(101: still paused), its sends stay pending",
        "/admin/accounts shows each owner its 2FA Creators paused (session_dead_reason otp_required)",
        "UI: the bell's Agency tab lists the 2FA notification as a link to Browserbase login",
        "UI: the row closes the bell and opens Creators with Browserbase login focused; the row is read (API)",
        "UI: the Creator's row shows the 'automations paused' badge naming Browserbase login",
    )),
    # slop/run session-health-otp --break --fault=session-dead-claim-not-atomic
    "session-dead-claim-not-atomic": Fault(_session_dead_claim_not_atomic, (
        "one session_dead notification per owner per 2FA Creator, opening Browserbase login; "
        "no other owner notified",
        "each affected owner's /events carried the notification and the pause; no other owner's did",
    )),
    # slop/run session-health-otp --break --fault=retired-read-not-rerun
    "retired-read-not-rerun": Fault(_retired_read_not_rerun, (
        "every concurrent inbox read of a 2FA Creator answered 502 with OF's 400 (upstream_status)",
    )),
    # slop/run browserbase-otp --break (the scenario's FAULT)
    "otp-code-never-consumed": Fault(_otp_code_never_consumed, (
        "API: a wrong 2FA code comes back as rejected and the job stays on the 2FA prompt",
        "API: the prompt back after a wrong code says rejected at once (inside OTP_VERIFY_S), never a fresh ask",
        "API: the right 2FA code signs in; the session is saved and linked to the owner",
        "API: a 2FA field that submits itself on the last digit: the code counts as sent (never \"couldn't "
        "type\"), a wrong one is rejected, the right one signs in",
        "OnlyFans' 2FA field received exactly the codes submitted, in order",
        "every 2FA code was sent with the 2FA form's own VERIFY button (by the field itself where it submits "
        "itself); the page's first button never",
        'card: a pasted "1234-5678" is the 8-digit code 12345678 (field, Submit on, what OnlyFans got)',
        "card: a wrong code shows the rejection and the field takes another code",
        "card: the right code links the account (job done, user_accounts row)",
        "card: Done on the linked screen (account + account details) saves and closes the modal",
        "phone: Browser login with the right 2FA code links the account (linked screen fits 390px with Done in "
        "view, job done, user_accounts row)",
    )),
    # slop/run browserbase-otp --break --fault=challenge-counts-hidden-frames
    "challenge-counts-hidden-frames": Fault(_challenge_counts_hidden_frames, (
        "API: a hidden captcha frame on OnlyFans' pages is never reported as a verification check "
        "(no status says challenge)",
    )),
    # slop/run runtime-switches --break (the scenario's FAULT)
    "runtime-switch-env-bypass": Fault(_runtime_switch_env_bypass, (
        "W7 switch on from Settings > System: no dispatch job for any DM sent while it is on",
    )),
    # slop/run trial-popup --break (the scenario's FAULT)
    "applied-drops-hide-trial-popup": Fault(_applied_drops_hide_trial_popup, (
        "GET /admin/settings/applied: hide_trial_popup true after the save",
        "UI: switch on, shell reloaded: no Free trial exceeded dialog",
    )),
    # slop/run trial-popup --break --fault=trial-popup-trusts-saved-applied (client side)
    # app/lib/appliedSettings.ts useAppliedSettingsAfterMount as before 2026-11-04: the nag decides from
    # the Applied answer the snapshot restored (fresh for 60 s, no refetch), so a pre-save false shows it.
    "trial-popup-trusts-saved-applied": Fault(None, (
        "UI: stored true, a stale saved Applied answer (false) restored: no Free trial exceeded dialog",
    ), browser=((r"\bstaleTime:\s*0(?=\s*[,}])", "staleTime: 60000"),  # appliedQuery's own staleTime
                (r"q\.isFetchedAfterMount\s*&&\s*!q\.isPlaceholderData", "true")),
        # next dev bundles appliedSettings.ts into each chunk the run loads: app/layout, app/page,
        # settings/layout, settings/[tab]/page (one match per pattern per load of each).
        browser_files=4, ts_files=1),
    # slop/run 2026-11-07-ai-chatter-nav --break (the scenario's FAULT, client side): app/lib/nav.ts's
    # Full AI Chatter link without `chatterHidden`, so a chatter's sidebar draws the owner-only page.
    "full-ai-chatter-shown-to-chatter": Fault(None, (
        "chatter (role ticks Auto-reply only): the sidebar shows My AI Chatter with Auto-reply and "
        "Get to know fans, no My Automations, no Full AI Chatter",
    ), browser=((r'(href:\s*\\?"/full-ai-chatter\\?",[^}]*?chatterHidden:\s*)(?:true|!0)', r"\g<1>false"),),
        # next dev's eval strings escape the quotes; nav.ts sits in each chunk the run loads.
        browser_files=4),
    # slop/run 2026-11-07-ai-chatter-nav --break --fault=sidebar-groups-not-accordion (client side):
    # app/components/shell/Sidebar.tsx before 2026-11-08: each group toggles on its own (a per-label
    # map, the page's group open until toggled), so every toggled group stays open. The click still
    # sets a fresh choice so the sidebar re-renders.
    "sidebar-groups-not-accordion": Fault(None, (
        "phone: opening My Automations (6 pages), then My AI Chatter (Auto-reply, "
        "Get to know fans, Full AI Chatter) leaves only My AI Chatter open",
    ), browser=(
        (r"openGroup\s*===\s*(?:undefined|void 0)\s*\?\s*holdsActive\s*:\s*openGroup\s*===\s*n\.label",
         "(globalThis.__slopToggled ??= {})[n.label] ?? holdsActive"),
        (r"label:\s*open\s*\?\s*null\s*:\s*n\.label",
         "label: (globalThis.__slopToggled[n.label] = !open, String(Math.random()))"),
    ), browser_files=1),
    # slop/run 2026-11-10-help-bot-links --break (client side): answerLinks.ts before 2026-11-10, a page
    # named in prose ("open Manage creators", "Settings has an Audit log page") left plain or on /settings.
    "help-links-prose-pages-unlinked": Fault(None, (
        "/help-center: every link in the answer has the expected text and exact href (prose page names "
        "link their page; a list sentence or one plain word does not borrow one)",
    ), browser=((r"\.\.\.NAMED,", ""), (r"head\.children \? namedBelow\(", "false ? namedBelow(")), browser_files=1),
    # slop/run 2026-11-11-assistant-do-auto-mass --break (client side): the agent's save posts what the form holds.
    # Two layers keep a Do it rule OFF, so the fault drops BOTH (either alone would mask it): ReadyMadeRuleEditor's
    # forced-OFF guard in its agent save (`if (agent) body.is_enabled = false;`, in the auto-mass and auto-post page
    # chunks) and doFlows.ts' "Leaving it OFF" step patch (layout chunk) -> the blank editor's `enabled: true` stands.
    # Each pattern must match (else INFRA): a reworded guard fails loudly, never a silent green.
    "assistant-do-skips-disabled": Fault(None, ("rule_saved_disabled",), browser=(
        (r"if(?:\s|\\n)*\((?:\s|\\n)*agent(?:\s|\\n)*\)(?:\s|\\n)*body\.is_enabled(?:\s|\\n)*=(?:\s|\\n)*(?:false|!1);?",
         ";"),
        (r"patch:(?:\s|\\n)*\{(?:\s|\\n)*enabled:(?:\s|\\n)*(?:false|!1),(?:\s|\\n)*dryRun:(?:\s|\\n)*(?:false|!1)"
         r"(?:\s|\\n)*\}", "patch: {}"),
    ), browser_files=3),
    # slop/run 2026-11-11-assistant-do-auto-mass --break --fault=assistant-edit-skips-second-account (relay side)
    "assistant-edit-skips-second-account": Fault(_assistant_edit_skips_second_account, ("edit_unsend_off_all_models",)),
    # slop/run 2026-11-12-assistant-siri-box --break (client side): markers.ts' parseMarkers keeps every sentence
    # whole (`s.includes(SLOT) ? stripFigures(s) : s` -> `s`), so a figure the model wrote beside a data marker
    # stays in the answer next to the live card. The pattern must match (else INFRA).
    "assistant-marker-figure-kept": Fault(None, ("figure_stripped",), browser=(
        (r"s\.includes\(SLOT\)(?:\s|\\n)*\?(?:\s|\\n)*stripFigures\(s\)(?:\s|\\n)*:(?:\s|\\n)*s(?=\))", "s"),
    ), browser_files=1),
    # slop/run 2026-10-26-fan-list-chips --break (the scenario's FAULT)
    "fan-list-owe-reply-last-sort-never-active": Fault(None, (
        "chips on screen: All, Owe reply, Pinned, Unread, With Tips, the pinned lists, Priority",
        "an extra sort turns the sort button active (blue), named by it, with its ✓, and puts unread rows first",
        "the sort menu lists Sort by, then Newest first, Amount spent, Spend + unread on top, Spend + recency,"
        " with no divider (1470px and a 390px phone)",
    ), browser_js=_FAN_LIST_OWE_REPLY_LAST_SORT_NEVER_ACTIVE),
    # slop/run 2026-10-26-fan-list-chips --break --fault=fan-search-every-keystroke (client side)
    # app/components/chat/FanList.tsx: the search box's text is sent at once, as before 2026-10-28,
    # so a name typed fast is a search per key; the rows still settle on the whole name's matches.
    "fan-search-every-keystroke": Fault(None, (
        "a Fan's name typed fast is one search, for the box's text, and the rows are its matches (one Creator)",
    ), browser=((r",\s*SEARCH_DEBOUNCE_MS,", ", 0,"),)),  # useTrailingDebounce's delay; `= 250` is its definition
    # slop/run 2026-10-28-dashboard-load --break (the scenario's FAULT). Since 2026-10-28 a return visit paints the
    # saved Total before any answer, so only the first visits wait: the budgets (return visits) stay green.
    "dashboard-total-waits-of-reads": Fault(None, (
        "Total earnings painted before the slow-proxy Creator's OnlyFans reads ended (it never waits on OF)",
    ), browser_js=_DASHBOARD_TOTAL_WAITS_OF_READS),
    # slop/run 2026-10-28-dashboard-load --break --fault=dashboard-total-not-saved
    "dashboard-total-not-saved": Fault(None, (
        "a visit with the saved query cache painted the saved Total before its revenue read answered, "
        "the figure the settled page shows",
        "lte: Total earnings painted within BUDGET_MS on a return visit",
        "slow4g: Total earnings painted within BUDGET_MS on a return visit",
    ), browser_js=_DASHBOARD_TOTAL_NOT_SAVED),
    # slop/run 2026-10-28-dashboard-load --break --fault=dashboard-offline-creator-reads-of
    "dashboard-offline-creator-reads-of": Fault(None, (
        "the session-less Creator sent no OnlyFans request (Dashboard visits, Creator reports' Per-model card) "
        "and its card shows 'Not connected'; on a first visit every live Creator's card read OF",
    ), browser_js=_DASHBOARD_OFFLINE_CREATOR_READS_OF),
    # slop/run 2026-10-28-dashboard-load --break --fault=boot-skeleton-not-drawn: the two first-paint checks.
    "boot-skeleton-not-drawn": Fault(None, (
        "Dashboard loads whose JS comes over the network (first, after-deploy): the page's frame (the earnings "
        "card's labels, placeholder bars for the figures) painted before the app's first relay read, and the "
        "settled page has no skeleton left",
        "Messages Pro, first visit: its frame (the Fan List's skeleton rows) painted before the app's first relay "
        "read, and the settled list shows Fan rows and no skeleton",
    ), browser_js=_BOOT_SKELETON_NOT_DRAWN),
    # slop/run 2026-10-28-dashboard-load --break --fault=page-placeholders-not-drawn: the page sweep alone.
    "page-placeholders-not-drawn": Fault(None, (
        "every signed-in page, its relay reads held: no blank area, spinner, 'Loading…' line or empty state "
        "before its first data (its layout with placeholder bars instead), and none of those left once the reads "
        "answer",
    ), browser_js=_PAGE_PLACEHOLDERS_NOT_DRAWN),
    "restore-stale-point": Fault(None, (
        "RPO: every DM box A took more than 2s before the kill is in the restored DB",
        "counts match per shard after recovery: restored + taken on box B, nothing else",
    ), stack=_restore_stale_point),
}

for _mod in sorted(Path(__file__).parent.glob("*_faults.py")):
    _more = importlib.import_module(f"{__package__}.{_mod.stem}" if __package__ else _mod.stem).register(Fault)
    if _more.keys() & FAULTS.keys():
        raise SystemExit(f"slop: {_mod.name} redefines faults {sorted(_more.keys() & FAULTS.keys())}")
    FAULTS.update(_more)


def apply(name: str | None) -> None:
    if not name:
        return
    if name not in FAULTS:
        raise SystemExit(f"slop: unknown fault {name!r}; known: {', '.join(FAULTS)}")
    if FAULTS[name].apply is not None:
        FAULTS[name].apply()


def apply_stack(name: str | None, fleet) -> None:
    """The harness-side half of a fault (lib/edge.Fleet calls it before the stack starts)."""
    if name and name in FAULTS and FAULTS[name].stack is not None:
        FAULTS[name].stack(fleet)


# --- vault sort label (rwl/vault-sort-humanstyle) ---
# slop/run 2026-10-29-state-reducers --break --fault=vault-sort-label-not-saved-in-sort
# app/hooks/useVaultCache.ts `sortOfFolders`: the folder sort label is not saved once OF took the sort (the pre-fix
# code saved it from the rail alone, so a sort from the OF-mirror Vault page or the new-post dialog left it stale).
# The rail's Done goes through `sortOfFolders` too: its own label still reads "Custom" (its state follows
# `sortOfFolders`' return), and after the reload the stored label reads "Default"; the OF-mirror Vault page's sort
# leaves it there too.
_reducers = importlib.import_module(f"{__package__}.reducers_faults" if __package__ else "reducers_faults")
if "vault-sort-label-not-saved-in-sort" in FAULTS:
    raise SystemExit("slop: faults.py redefines vault-sort-label-not-saved-in-sort")
FAULTS["vault-sort-label-not-saved-in-sort"] = Fault(
    None, (_reducers.VAULT_SORT_LABEL, _reducers.VAULT_MIRROR_SORT_LABEL), browser=(
        (r"\(0,\s*[\w$]+\.saveFolderSort\)\(accountId,", "((..._) => {})(accountId,"),
    ), browser_files=_reducers.USE_VAULT_CACHE_FILES)

# Vault picker's client regressions. Each rewrite applies only to the served next-dev bundle; the real UI and
# relay still run. The scenarios retain their existing default FAULT, while --fault can select either of these.
FAULTS["vault-gif-loop-cap-removed"] = Fault(
    None, ("ui_gif_picker_caps_attached_loops_and_detaches_offscreen",),
    browser=((r"MAX_GIF_LOOPS\s*=\s*4", "MAX_GIF_LOOPS = 40"),), browser_files=1)
FAULTS["vault-picker-refresh-pending-hidden"] = Fault(
    None, ("vault_picker_refresh_pending_single_post_and_failure_note",),
    browser=((r"isPending:\s*pending", "isPending: false"),), browser_files=2)


# --- OF call counter (fetch-diet ticket 01) ---
# slop/run of-call-counter --break: service/of_call_counter.record counts only 2xx answers (the 429s, 5xx, 4xx and
# no-answer calls OF saw are dropped), so the file stops equalling the wire.
def _of_counter_drops_errors() -> None:
    import of_call_counter
    real = of_call_counter.record

    def only_ok(account_id, method, url, status):
        if isinstance(status, int) and 200 <= status < 300:
            real(account_id, method, url, status)

    of_call_counter.record = only_ok


if "of-counter-drops-errors" in FAULTS:
    raise SystemExit("slop: faults.py redefines of-counter-drops-errors")
FAULTS["of-counter-drops-errors"] = Fault(_of_counter_drops_errors, ("counts_match_wire",))


# --- Pins cache + wall scan identity (fetch-diet ticket 09) ---
# slop/run slow-conn --break --fault=pins-uncached: server._pins_cache_ttl_s answers 0 (today's uncached read), so
# every chat open re-reads OF's /pinned. --fault=wall-calls-me: the wall-media scan asks OF's /users/me for the
# Creator's id again (vault_sends_api before the cut).
PINS_ONCE = "PINS_ONCE: opens of one chat inside the pins TTL make one /pinned OF call (two in a row, three at once)"
WALL_NO_ME = "WALL_NO_ME: wall-media warms add no /users/me (counter rows under the route; its posts reads all there)"


def _pins_uncached() -> None:
    import server
    server._pins_cache_ttl_s = lambda: 0.0


def _wall_calls_me() -> None:
    import vault_sends_api

    def old(_account_id, client):  # the scan before the cut: a /users/me read, an int id
        my_id = client.me().get("id")
        return my_id if isinstance(my_id, int) else None

    vault_sends_api._session_user_id = old


for _name in ("pins-uncached", "wall-calls-me"):
    if _name in FAULTS:
        raise SystemExit(f"slop: faults.py redefines {_name}")
FAULTS["pins-uncached"] = Fault(_pins_uncached, (PINS_ONCE,))
FAULTS["wall-calls-me"] = Fault(_wall_calls_me, (WALL_NO_ME,))


# --- Unread warm reuse (fetch-diet ticket 16) ---
# slop/run slow-conn --break --fault=warm-not-reused: the fix reverted in flight (a client fault on the production
# build's Messages Pro chunk, slow-connections' warm leg routes it): the inbox Thread and the Fan List's press
# warm-up lose UNREAD_WARM_REUSE_MS, so an open 15-20 s after the unread warm reads the head page again.
WARM_REUSED = ("WARM_REUSED: a Fan warmed by the unread warm and opened inside 20 s makes one head GET (the warm's), "
               "in the browser and on OF's wire")
WARM_FRESH = ("WARM_FRESH: a Fan DM after the warm shows on the reused open; an open past 20 s of the warm reads "
              "the head page again")
if "warm-not-reused" in FAULTS:
    raise SystemExit("slop: faults.py redefines warm-not-reused")
FAULTS["warm-not-reused"] = Fault(None, (WARM_REUSED,), browser=(
    (r"(insightsOpenAtStart:[^,{}]+,)prefetchWindowMs:[\w$.]+,", r"\1"),
    (r"warmWindowMs:[\w$.]+,(actions:)", r"\1")), browser_files=1)
# --fault=warm-window-wide: the inbox window widened to 60 s in the same chunk, so the open 23 s after the warm
# rides it too (no second head read).
FAULTS["warm-window-wide"] = Fault(None, (WARM_FRESH,), browser=(
    (r"(insightsOpenAtStart:[^,{}]+,prefetchWindowMs:)[\w$.]+,", r"\g<1>6e4,"),
    (r"(warmWindowMs:)[\w$.]+,(actions:)", r"\g<1>6e4,\2")), browser_files=1)


# --- mass send reads no roster (the Audience crawl deleted, 2026-11-12) ---
# slop/run mass-send-no-roster-reads --break: every OF mass send (both paths call OFClient.send_mass_message) is
# followed by one fans and one following roster page, the deleted crawl's bug class.
def _mass_send_reads_roster() -> None:
    import of_sends
    real = of_sends.SendsMixin.send_mass_message

    def then_roster(self, *a, **kw):
        out = real(self, *a, **kw)
        for read in (self.subscribers, self.following):
            try:
                read(limit=50, offset=0)
            except Exception:  # noqa: BLE001 — the read is the fault, its answer is not
                pass
        return out

    of_sends.SendsMixin.send_mass_message = then_roster


for _name in ("mass-send-reads-roster",):
    if _name in FAULTS:
        raise SystemExit(f"slop: faults.py redefines {_name}")
FAULTS["mass-send-reads-roster"] = Fault(_mass_send_reads_roster, ("no_roster_reads",))
