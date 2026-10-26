"""Break-it-once: named product faults the relay wrapper can inject.

`slop/run <scenario> --break` runs a green baseline, then the same run with the
scenario's FAULT applied. CAUGHT means every check the fault declares in
`targets` went PASS -> FAIL; any other check that changed is reported as noise
and catches nothing. If a targeted check stays green, the mutation is NOT
caught: the invariants are blind to it.

A fault patches a real product function inside the throwaway relay process
(never the repo files). Add one per bug class a scenario claims to catch, and
name in `targets` the exact check names (ctx.check) that must see it.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
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


# The Fan List as before ADR-0003's 2026-10-26 amendment, in the two ways its
# scenario must see: Owe reply laid out last in the chip row, where the "+"
# overflow sat, and a sort button that never looks active (not pressed, not
# blue) whatever order is in force. Layout and attributes only, so React's tree
# and the console are untouched.
_FAN_LIST_OWE_REPLY_LAST_SORT_NEVER_ACTIVE = """(() => {
  const css = '[role=group][aria-label="Fan List filters"] button[title*=" extra \u2014 Owe reply"]'
    + ' { order: 99; }';
  const calm = () => document.querySelectorAll('button[aria-label^="Sort: "]').forEach((b) => {
    if (b.getAttribute("aria-pressed") === "true") b.setAttribute("aria-pressed", "false");
    if (b.classList.contains("bg-accent")) {
      b.classList.remove("bg-accent", "text-white", "border-accent");
      b.classList.add("text-fg-dim");
    }
  });
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
    browser: str | None = None  # init script in every page actors/ui opens: a bug in the app's browser code
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
    ), browser=_NOTIF_CLICK_OPENS_BROWSER_TAB, desktop=_NOTIF_CLICK_DESKTOP_IGNORES_MESSAGES_PRO),
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
    # slop/run session-health-otp --break (the scenario's FAULT)
    "otp-state-not-session-dead": Fault(_otp_state_not_session_dead, (
        "account_health flags exactly the 2FA Creators, reason otp_required",
        "one session_dead notification per owner per 2FA Creator, opening Browserbase login; "
        "no other owner notified",
        "each affected owner's /events carried the notification and the pause; no other owner's did",
        "a Creator with no automations is flagged by its owner's inbox read alone (via=proxy): "
        "otp_required, one notification",
        "the WS pump met the 2FA demand once and parked: per 2FA Creator at most 2 /users/me over "
        ">= 20 s (the pump's reconnect, the probe's), no reconnect, the pump exited and "
        "supervisor passes left it parked",
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
    # slop/run 2026-10-26-fan-list-chips --break (the scenario's FAULT)
    "fan-list-owe-reply-last-sort-never-active": Fault(None, (
        "chips on screen: All, Owe reply, Pinned, Unread, With Tips, the pinned lists, Priority",
        "an extra sort turns the sort button active (blue), named by it, with its ✓, and puts unread rows first",
    ), browser=_FAN_LIST_OWE_REPLY_LAST_SORT_NEVER_ACTIVE),
}


def apply(name: str | None) -> None:
    if not name:
        return
    if name not in FAULTS:
        raise SystemExit(f"slop: unknown fault {name!r}; known: {', '.join(FAULTS)}")
    if FAULTS[name].apply is not None:
        FAULTS[name].apply()
