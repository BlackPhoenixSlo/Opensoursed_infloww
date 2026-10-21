/**
 * events.ts — EventSource client + a typed dispatcher.
 *
 * The browser opens one EventSource per session (per scope). The relay's
 * `/events?scope=...` endpoint feeds it. When an event arrives, dispatch
 * fires per-event-type listeners *and* a wildcard catch-all.
 *
 * Reconnect: EventSource auto-reconnects on socket close and resends the
 * last `id:` it saw; the relay replays what it still holds after it, or
 * sends `resync` when it no longer reaches back that far. When the browser
 * gives up (non-200, e.g. a relay restart behind the proxy) we reopen
 * ourselves with backoff and pass that id as `?last_event_id=`.
 *
 * Concurrency: a single EventSource per scope; multiple components
 * subscribe to the same one via `on(eventType, fn)`. Clean up by calling
 * the returned unsubscriber on unmount.
 */

import { resolveShareToken } from "./shareToken";

export type Scope = "all" | `model:${string}`;

export interface EventEnvelope {
  __account_id?: string;
  __account_name?: string;
  __account_color?: string;
  [key: string]: unknown;
}

type Listener = (e: EventEnvelope, rawType: string) => void;

// 2.25× the 20 s backend heartbeat: two missed pings absorb network/GC
// hiccups before isConnected degrades. Tighter than this is jittery;
// looser delays the offline-poll kick-in.
const STALE_MS = 45_000;
// Cheap tick so the stale->fresh transition fires for `onStateChange`
// listeners without busy-polling. STALE_MS / STALE_CHECK_MS ≈ 9 ticks
// inside the freshness window — plenty to debounce.
const STALE_CHECK_MS = 5_000;
// Our own reopen after the browser gives up: 5 s, doubling to 60 s.
const RETRY_MIN_MS = 5_000;
const RETRY_MAX_MS = 60_000;

/** refetchInterval for a query that SSE keeps fresh: a slow safety poll
 *  while the stream is live, the old fast poll while it is not. */
export function ssePoll(liveMs: number, offlineMs: number): () => number {
  return () => (eventBus.isConnected() ? liveMs : offlineMs);
}

class EventBus {
  private es: EventSource | null = null;
  private currentScope: Scope | null = null;
  // Listeners keyed by event_type. The wildcard "*" key catches everything.
  private byType = new Map<string, Set<Listener>>();
  // Reconnect throttle — EventSource handles its own backoff for socket
  // failures, but our explicit `.close()` calls when scope changes need
  // to avoid thrash if the user clicks the model switcher rapidly.
  private restartTimer: ReturnType<typeof setTimeout> | null = null;
  // Last time ANY SSE frame arrived (including the named `ping` heartbeat).
  // Drives `isConnected()` — see STALE_MS. Socket-OPEN alone does NOT bump
  // this: a reconnected socket with a hung upstream pump must read as
  // disconnected so heavier-poll consumers kick in.
  private lastEventAt = 0;
  // Mirror of the last value reported to state listeners, so
  // `notifyStateChange` only fires on real transitions.
  private lastReportedConnected = false;
  private staleCheckTimer: ReturnType<typeof setInterval> | null = null;
  private stateListeners = new Set<(connected: boolean) => void>();
  // The browser's last-seen event id (MessageEvent.lastEventId, which also
  // follows id-only frames), for reopening after the browser gave up.
  private lastEventId = "";
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private retryMs = RETRY_MIN_MS;
  // Idle mode (`pause`): no socket, and scope changes wait for `resume`.
  private paused = false;

  /** True iff the SSE socket is OPEN *and* an event has arrived within
   *  STALE_MS. A half-dead pipe (socket open, upstream stalled) reads false. */
  isConnected(): boolean {
    // No socket yet (also where there is no EventSource at all, e.g. jsdom).
    if (!this.es) return false;
    const fresh = Date.now() - this.lastEventAt < STALE_MS;
    return this.es.readyState === EventSource.OPEN && fresh;
  }

  /** Subscribe to connection state transitions. Fires immediately with
   *  the current state, then again on every open/close. Returns an
   *  unsubscriber the caller MUST call on unmount. */
  onStateChange(fn: (connected: boolean) => void): () => void {
    this.stateListeners.add(fn);
    try { fn(this.isConnected()); } catch { /* ignore listener errors */ }
    return () => { this.stateListeners.delete(fn); };
  }

  private notifyStateChange() {
    const next = this.isConnected();
    if (next === this.lastReportedConnected) return;
    this.lastReportedConnected = next;
    for (const fn of this.stateListeners) {
      try { fn(next); } catch (err) { console.error("[events] state listener error", err); }
    }
  }

  private bumpLastEventAt() {
    this.lastEventAt = Date.now();
    this.notifyStateChange();
  }

  private ensureStaleCheck() {
    if (this.staleCheckTimer) return;
    this.staleCheckTimer = setInterval(() => this.notifyStateChange(), STALE_CHECK_MS);
  }

  /** Switch the live scope. Idempotent — calling with the same scope is a no-op. */
  setScope(scope: Scope) {
    if (this.currentScope === scope) return;
    this.currentScope = scope;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = setTimeout(() => this.reconnect(), 50);
  }

  /** Idle mode: close the stream until `resume`. */
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.reconnect();
  }

  /** Leave idle mode: reopen from the last event id, so the relay replays
   *  what the tab missed (or sends `resync` when it can no longer). */
  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.reconnect(true);
  }

  isPaused(): boolean {
    return this.paused;
  }

  /** Tear down + reopen. Called on scope changes + on share-token rotation,
   *  and with `resume` after the browser stopped retrying on its own. While
   *  paused it only tears down. */
  private reconnect(resume = false) {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    // Force the freshness window closed so consumers see "disconnected"
    // until the first event lands on the new socket.
    this.lastEventAt = 0;
    this.notifyStateChange();
    const scope = this.currentScope;
    if (!scope || this.paused) return;
    const tok = resolveShareToken();
    const qs = new URLSearchParams({ scope });
    if (tok) qs.set("t", tok);
    if (resume && this.lastEventId) qs.set("last_event_id", this.lastEventId);
    const url = `/events?${qs.toString()}`;
    const es = new EventSource(url);
    this.es = es;
    this.ensureStaleCheck();

    // Relay sets the SSE `event:` line to the OF event type. We listen
    // on a wildcard via `onmessage`, and ALSO add specific listeners
    // when callers ask for them — those use addEventListener on the
    // event-type name directly (DOM API, not our dispatcher).
    //
    // Deliberately do NOT bump lastEventAt on onopen alone: a reconnect
    // can succeed while the upstream pump is hung, and the freshness
    // boundary is what catches that.
    es.onopen = () => {
      this.retryMs = RETRY_MIN_MS;
      this.notifyStateChange();
    };
    es.onmessage = (msg) => {
      this.noteId(msg);
      this.bumpLastEventAt();
      this.dispatch("message", msg.data);
    };
    es.onerror = (err) => {
      // SSE silently reconnects — we just log a low-level event so
      // listeners can show a "reconnecting…" pill if they care. Reset
      // freshness so isConnected flips false even while the browser
      // retries underneath.
      this.lastEventAt = 0;
      this.notifyStateChange();
      this.dispatch("__error", JSON.stringify({ readyState: this.es?.readyState }));
      void err;
      // CLOSED means the browser will not retry (a non-200 answer).
      if (this.es === es && es.readyState === EventSource.CLOSED && !this.retryTimer) {
        this.retryTimer = setTimeout(() => this.reconnect(true), this.retryMs);
        this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
      }
    };

    // Backend heartbeat — bump freshness, do NOT dispatch (no consumer
    // should care about pings). Without this, an idle relay (no real
    // events) would degrade to "disconnected" every 45 s.
    es.addEventListener("ping", (msg) => {
      this.noteId(msg as MessageEvent);
      this.bumpLastEventAt();
    });

    // Re-register every known type-listener against the new EventSource.
    for (const type of this.byType.keys()) {
      if (type === "*" || type === "__error") continue;
      this.attachNativeListener(es, type);
    }
  }

  private attachNativeListener(es: EventSource, type: string) {
    es.addEventListener(type, (msg) => {
      this.noteId(msg as MessageEvent);
      this.bumpLastEventAt();
      this.dispatch(type, (msg as MessageEvent).data);
    });
  }

  private noteId(msg: MessageEvent) {
    if (msg.lastEventId) this.lastEventId = msg.lastEventId;
  }

  private dispatch(type: string, raw: string) {
    let parsed: EventEnvelope = {};
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = { __raw: raw } as EventEnvelope;
    }
    const exact = this.byType.get(type);
    const wild = this.byType.get("*");
    if (exact) for (const fn of exact) safe(fn, parsed, type);
    if (wild) for (const fn of wild) safe(fn, parsed, type);
  }

  /**
   * Subscribe to an event type. `"*"` catches every event.
   * Returns an unsubscriber the caller MUST call on unmount.
   */
  on(type: string, fn: Listener): () => void {
    if (!this.byType.has(type)) {
      this.byType.set(type, new Set());
      // If we already have a live EventSource, register the named-event
      // listener on it now so new subscribers don't miss types they care
      // about that the wildcard onmessage doesn't see.
      if (this.es && type !== "*" && type !== "__error") {
        this.attachNativeListener(this.es, type);
      }
    }
    this.byType.get(type)!.add(fn);
    return () => {
      this.byType.get(type)?.delete(fn);
    };
  }
}

function safe(fn: Listener, e: EventEnvelope, type: string) {
  try {
    fn(e, type);
  } catch (err) {
    console.error("[events] listener error", err);
  }
}

// Module-level singleton — only one EventSource regardless of how many
// components subscribe.
export const eventBus = new EventBus();
