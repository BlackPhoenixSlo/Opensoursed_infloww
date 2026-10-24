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
 * Batches: while a stream runs hot the relay groups its events into one
 * `event: batch` frame (`[{id, type, data}, ...]`, oldest first, the frame's
 * id = its last member's; service/events.py "Load-adaptive batching"). Each
 * member is dispatched exactly as if it had come as its own frame, all inside
 * one React Query notify batch, so a 50-event frame is one render pass.
 *
 * Adaptive apply: the tab measures its own arrival rate (events per second
 * over the last second, batch members counted). At or under
 * HOT_EVENTS_PER_S every event is applied the moment it lands; above it,
 * events (single or batch) queue and apply together on the next animation
 * frame, in arrival order, inside one notify batch. A flood then costs at
 * most one list update per painted frame, and a DM waits at most a frame
 * (the relay already batches a hot stream into 100-250 ms frames, so a
 * longer window here only adds latency: a fixed 250 ms one was ~260 ms of
 * every DM's time to screen). Where frames do not run (a hidden tab) the
 * queue flushes after APPLY_WINDOW_MS instead.
 *
 * Concurrency: a single EventSource per scope; multiple components
 * subscribe to the same one via `on(eventType, fn)`. Clean up by calling
 * the returned unsubscriber on unmount.
 */

import { notifyManager } from "@tanstack/react-query";

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
// Adaptive apply (see the header). Knobs: NEXT_PUBLIC_SSE_HOT_EVPS,
// NEXT_PUBLIC_SSE_APPLY_WINDOW_MS. A quiet inbox (≤ 2 ev/s) stays instant;
// a hot one applies on the next frame, or after 250 ms where frames do not
// run (hidden tab), well inside the 2 s SSE-lag budget.
export const HOT_EVENTS_PER_S = envNum(process.env.NEXT_PUBLIC_SSE_HOT_EVPS, 2);
export const APPLY_WINDOW_MS = envNum(process.env.NEXT_PUBLIC_SSE_APPLY_WINDOW_MS, 250);
const RATE_SPAN_MS = 1_000;

function envNum(v: string | undefined, fallback: number): number {
  const n = Number(v);
  return v != null && v !== "" && Number.isFinite(n) && n >= 0 ? n : fallback;
}

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
  // Adaptive apply: [arrivedAt, count] over the last RATE_SPAN_MS, and the
  // events waiting for the current window.
  private arrivals: [number, number][] = [];
  private pending: [string, EventEnvelope][] = [];
  private applyTimer: ReturnType<typeof setTimeout> | null = null;
  private applyFrame: number | null = null;

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
    // Events already received apply before anything from the next stream.
    this.flushPending();
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

    es.addEventListener("batch", (msg) => {
      this.noteId(msg as MessageEvent);
      this.bumpLastEventAt();
      this.dispatchBatch((msg as MessageEvent).data);
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
    // Connection signals are not data: never held back.
    if (type === "__error") this.emit(type, parsed);
    else this.admit([[type, parsed]]);
  }

  /** Apply now while the stream is quiet; above HOT_EVENTS_PER_S (or while
   *  a flush is pending, so order holds) queue for the next frame's flush. */
  private admit(events: [string, EventEnvelope][]) {
    if (!events.length) return;
    const now = Date.now();
    this.arrivals.push([now, events.length]);
    while (this.arrivals.length && now - this.arrivals[0][0] >= RATE_SPAN_MS) this.arrivals.shift();
    let rate = 0;
    for (const [, n] of this.arrivals) rate += n;
    if (!this.applyTimer && rate <= HOT_EVENTS_PER_S) {
      this.applyAll(events);
      return;
    }
    for (const e of events) this.pending.push(e);
    if (this.applyTimer) return;
    this.applyTimer = setTimeout(() => this.flushPending(), APPLY_WINDOW_MS);
    if (typeof requestAnimationFrame === "function") {
      this.applyFrame = requestAnimationFrame(() => this.flushPending());
    }
  }

  private flushPending() {
    if (this.applyTimer) clearTimeout(this.applyTimer);
    if (this.applyFrame != null) cancelAnimationFrame(this.applyFrame);
    this.applyTimer = null;
    this.applyFrame = null;
    const q = this.pending;
    this.pending = [];
    this.applyAll(q);
  }

  /** One notify batch, so the cache writes they make render once. */
  private applyAll(events: [string, EventEnvelope][]) {
    if (!events.length) return;
    if (events.length === 1) {
      this.emit(events[0][0], events[0][1]);
      return;
    }
    notifyManager.batch(() => {
      for (const [t, e] of events) this.emit(t, e);
    });
  }

  /** A `batch` frame: each member as if it had come on its own. Only types
   *  someone listens for, as a single frame only reaches a named listener. */
  private dispatchBatch(raw: string) {
    let members: { type?: unknown; data?: unknown }[];
    try {
      members = JSON.parse(raw);
    } catch {
      return;
    }
    if (!Array.isArray(members)) return;
    const events: [string, EventEnvelope][] = [];
    for (const m of members) {
      if (typeof m?.type !== "string" || !this.byType.has(m.type)) continue;
      events.push([m.type, (m.data ?? {}) as EventEnvelope]);
    }
    this.admit(events);
  }

  private emit(type: string, parsed: EventEnvelope) {
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
