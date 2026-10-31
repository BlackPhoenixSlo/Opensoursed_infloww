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
 * ourselves and pass that id as `?last_event_id=`.
 *
 * Batches: while a stream runs hot the relay groups its events into one
 * `event: batch` frame (`[{id, type, data}, ...]`, oldest first, the frame's
 * id = its last member's; service/events.py "Load-adaptive batching"). Each
 * member is dispatched exactly as if it had come as its own frame, all inside
 * one React Query notify batch, so a 50-event frame is one render pass.
 *
 * Backoff, idle mode, freshness and adaptive apply are eventBusReducer.ts's
 * rules (its header); this file is their I/O.
 *
 * Concurrency: a single EventSource per scope; multiple components
 * subscribe to the same one via `on(eventType, fn)`. Clean up by calling
 * the returned unsubscriber on unmount.
 */

import { notifyManager } from "@tanstack/react-query";

import {
  type BusEffect, type BusInput, type BusState, type Decision, type EventEnvelope, type Queued, type Scope,
  decide, eventsUrl, follow, initialBusState, isConnected,
} from "./eventBusReducer";
import { resolveShareToken } from "./shareToken";

export type { EventEnvelope, Scope } from "./eventBusReducer";

type Listener = (e: EventEnvelope, rawType: string) => void;

// Cheap tick so the stale->fresh transition fires for `onStateChange`
// listeners without busy-polling. STALE_MS / STALE_CHECK_MS ≈ 9 ticks
// inside the freshness window — plenty to debounce.
const STALE_CHECK_MS = 5_000;

/** refetchInterval for a query that SSE keeps fresh: a slow safety poll
 *  while the stream is live, the old fast poll while it is not. */
export function ssePoll(liveMs: number, offlineMs: number): () => number {
  return () => (eventBus.isConnected() ? liveMs : offlineMs);
}

/** The I/O shell around eventBusReducer's `decide` / `follow`: EventSource
 *  callbacks, idle mode and timers become inputs; the effects returned are
 *  performed here, in order. The listener registry and JSON parsing are the
 *  shell's. */
class EventBus {
  private state: BusState = initialBusState;
  private es: EventSource | null = null;
  // Listeners keyed by event_type. The wildcard "*" key catches everything.
  private byType = new Map<string, Set<Listener>>();
  private staleCheckTimer: ReturnType<typeof setInterval> | null = null;
  private stateListeners = new Set<(connected: boolean) => void>();

  /** True iff the SSE socket is OPEN *and* an event has arrived within
   *  STALE_MS. A half-dead pipe (socket open, upstream stalled) reads false. */
  isConnected(): boolean {
    return isConnected(this.state, this.ready(), Date.now());
  }

  /** Subscribe to connection state transitions. Fires immediately with
   *  the current state, then again on every open/close. Returns an
   *  unsubscriber the caller MUST call on unmount. */
  onStateChange(fn: (connected: boolean) => void): () => void {
    this.stateListeners.add(fn);
    try { fn(this.isConnected()); } catch { /* ignore listener errors */ }
    return () => { this.stateListeners.delete(fn); };
  }

  /** Switch the live scope. Idempotent — calling with the same scope is a no-op. */
  setScope(scope: Scope) {
    this.send({ type: "SetScope", scope });
  }

  /** Idle mode: close the stream until `resume`. */
  pause() {
    this.send({ type: "Pause" });
  }

  /** Leave idle mode: reopen from the last event id, so the relay replays
   *  what the tab missed (or sends `resync` when it can no longer). */
  resume() {
    this.send({ type: "Resume" });
  }

  isPaused(): boolean {
    return this.state.paused;
  }

  /** The current socket's readyState (null = none; also where there is no EventSource, e.g. jsdom). */
  private ready(): number | null {
    return this.es ? this.es.readyState : null;
  }

  /** Decide and perform. A listener that calls back into the bus (pause,
   *  setScope) is decided at once, nested (eventBusReducer's header). */
  private send(ev: BusInput) {
    this.run(decide(this.state, ev));
  }

  private run({ state, effects }: Decision) {
    this.state = state;
    for (const fx of effects) this.perform(fx);
  }

  private perform(fx: BusEffect) {
    switch (fx.type) {
      case "Open":
        this.open(eventsUrl(fx.scope, resolveShareToken(), fx.lastEventId), fx.gen);
        return;
      case "Close":
        this.es?.close();
        this.es = null;
        return;
      case "After": {
        // The first of the two to fire cancels the other (a hidden tab piles up no frame callbacks).
        let frame: number | null = null;
        const fire = () => {
          clearTimeout(timer);
          if (frame !== null) cancelAnimationFrame(frame);
          this.send(fx.fire);
        };
        const timer = setTimeout(fire, fx.ms);
        if (fx.frame && typeof requestAnimationFrame === "function") frame = requestAnimationFrame(fire);
        return;
      }
      case "Then":
        this.run(follow(this.state, fx.event, this.ready()));
        return;
      case "Apply":
        this.applyAll(fx.events);
        return;
      case "NotifyConnected":
        for (const fn of this.stateListeners) {
          try { fn(fx.connected); } catch (err) { console.error("[events] state listener error", err); }
        }
        return;
    }
  }

  private open(url: string, gen: number) {
    const es = new EventSource(url);
    this.es = es;
    if (!this.staleCheckTimer) {
      this.staleCheckTimer = setInterval(
        () => this.send({ type: "StaleTick", now: Date.now(), ready: this.ready() }), STALE_CHECK_MS);
    }

    // Relay sets the SSE `event:` line to the OF event type. We listen
    // on a wildcard via `onmessage`, and ALSO add specific listeners
    // when callers ask for them — those use addEventListener on the
    // event-type name directly (DOM API, not our dispatcher).
    es.onopen = () => this.send({ type: "Opened", now: Date.now(), ready: this.ready() });
    es.onmessage = (msg) => this.frame(msg, [["message", parse(msg.data)]]);
    // SSE silently reconnects; listeners get an `__error` event so they can
    // show a "reconnecting…" pill if they care.
    es.onerror = () => this.send({ type: "Errored", now: Date.now(), ready: this.ready(), gen });

    // Backend heartbeat — freshness only, nothing dispatched (no consumer
    // should care about pings). Without this, an idle relay (no real
    // events) would degrade to "disconnected" every 45 s.
    es.addEventListener("ping", (msg) => this.frame(msg as MessageEvent, []));
    es.addEventListener("batch", (msg) => this.frame(msg as MessageEvent, this.batchMembers((msg as MessageEvent).data)));

    // Re-register every known type-listener against the new EventSource.
    for (const type of this.byType.keys()) {
      if (type === "*" || type === "__error") continue;
      this.attachNativeListener(es, type);
    }
  }

  private attachNativeListener(es: EventSource, type: string) {
    es.addEventListener(type, (msg) => this.frame(msg as MessageEvent, [[type, parse((msg as MessageEvent).data)]]));
  }

  private frame(msg: MessageEvent, events: Queued[]) {
    this.send({ type: "Frame", now: Date.now(), ready: this.ready(), id: msg.lastEventId, events });
  }

  /** One notify batch, so the cache writes they make render once. */
  private applyAll(events: Queued[]) {
    if (!events.length) return;
    if (events.length === 1) {
      this.emit(events[0][0], events[0][1]);
      return;
    }
    notifyManager.batch(() => {
      for (const [t, e] of events) this.emit(t, e);
    });
  }

  /** A `batch` frame's members, each as if it had come on its own. Only types
   *  someone listens for, as a single frame only reaches a named listener. */
  private batchMembers(raw: string): Queued[] {
    let members: { type?: unknown; data?: unknown }[];
    try {
      members = JSON.parse(raw);
    } catch {
      return [];
    }
    if (!Array.isArray(members)) return [];
    const events: Queued[] = [];
    for (const m of members) {
      if (typeof m?.type !== "string" || !this.byType.has(m.type)) continue;
      events.push([m.type, (m.data ?? {}) as EventEnvelope]);
    }
    return events;
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

function parse(raw: string): EventEnvelope {
  try {
    return JSON.parse(raw);
  } catch {
    return { __raw: raw } as EventEnvelope;
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
