import { notifyManager } from "@tanstack/react-query";

import {
  type BusEffect, type BusInput, type BusState, type Decision, type EventEnvelope, type Queued, type Scope,
  decide, eventsUrl, follow, initialBusState, isConnected,
} from "./eventBusReducer";
import { resolveShareToken } from "./shareToken";
import { serverOffset, setRelayOffset } from "./ageClock";

export type { EventEnvelope, Scope } from "./eventBusReducer";

type Listener = (e: EventEnvelope, rawType: string) => void;

const STALE_CHECK_MS = 5_000;

export function ssePoll(liveMs: number, offlineMs: number): () => number {
  return () => (eventBus.isConnected() ? liveMs : offlineMs);
}

class EventBus {
  private state: BusState = initialBusState;
  private es: EventSource | null = null;
  private byType = new Map<string, Set<Listener>>();
  private staleCheckTimer: ReturnType<typeof setInterval> | null = null;
  private stateListeners = new Set<(connected: boolean) => void>();

  isConnected(): boolean {
    return isConnected(this.state, this.ready(), Date.now());
  }

  onStateChange(fn: (connected: boolean) => void): () => void {
    this.stateListeners.add(fn);
    try { fn(this.isConnected()); } catch { }
    return () => { this.stateListeners.delete(fn); };
  }

  setScope(scope: Scope) {
    this.send({ type: "SetScope", scope });
  }

  pause() {
    this.send({ type: "Pause" });
  }

  resume() {
    this.send({ type: "Resume" });
  }

  isPaused(): boolean {
    return this.state.paused;
  }

  private ready(): number | null {
    return this.es ? this.es.readyState : null;
  }

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

    es.onopen = () => this.send({ type: "Opened", now: Date.now(), ready: this.ready() });
    es.onmessage = (msg) => this.frame(msg, [["message", parse(msg.data)]]);
    es.onerror = () => this.send({ type: "Errored", now: Date.now(), ready: this.ready(), gen });

    es.addEventListener("ping", (msg) => this.frame(msg as MessageEvent, this.pingEvents((msg as MessageEvent).data)));
    es.addEventListener("batch", (msg) => this.frame(msg as MessageEvent, this.batchMembers((msg as MessageEvent).data)));

    for (const type of this.byType.keys()) {
      if (NOT_NATIVE.has(type)) continue;
      this.attachNativeListener(es, type);
    }
  }

  private attachNativeListener(es: EventSource, type: string) {
    es.addEventListener(type, (msg) => this.frame(msg as MessageEvent, [[type, parse((msg as MessageEvent).data)]]));
  }

  private frame(msg: MessageEvent, events: Queued[]) {
    this.send({ type: "Frame", now: Date.now(), ready: this.ready(), id: msg.lastEventId, events });
  }

  // Every ping's ts sets the Relay-clock offset: a ping is never replayed, an event's `now` is as old as its send.
  private pingEvents(raw: string): Queued[] {
    const p = parse(raw);
    if (typeof p.ts === "number" && Number.isFinite(p.ts)) setRelayOffset(serverOffset(p.ts * 1000, Date.now()));
    if (!this.byType.has("ping")) return [];
    const fresh = p.fresh;
    return fresh && typeof fresh === "object" && !Array.isArray(fresh) ? [["ping", p]] : [];
  }

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

  on(type: string, fn: Listener): () => void {
    if (!this.byType.has(type)) {
      this.byType.set(type, new Set());
      if (this.es && !NOT_NATIVE.has(type)) {
        this.attachNativeListener(this.es, type);
      }
    }
    this.byType.get(type)!.add(fn);
    return () => {
      this.byType.get(type)?.delete(fn);
    };
  }
}

const NOT_NATIVE = new Set(["*", "__error", "ping"]);

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

export const eventBus = new EventBus();
