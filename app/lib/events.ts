import { notifyManager } from "@tanstack/react-query";

import {
  type BusEffect, type BusInput, type BusState, type Decision, type EventEnvelope, type Queued, type Scope,
  decide, eventsUrl, follow, initialBusState, isConnected,
} from "./eventBusReducer";
import {
  accountLive, allLive, blocked, cellBusReducer, downAccounts, INITIAL_CELL_BUS, liveChanges, protoOf, streamDiff,
  INITIAL_MAP_LOAD, mapLoadReducer, type CellBusState, type Proto,
} from "./cellBusReducer";
import { cellMode } from "./cellFlag";
import { currentCellMap, loadCellMap, onCellMap, setStreamGrey } from "./cellMap";
import type { CellMap } from "./cellInbox";
import { RelayError } from "./relay";
import { resolveShareToken } from "./shareToken";
import { serverOffset, setRelayOffset } from "./ageClock";

export type { EventEnvelope, Scope } from "./eventBusReducer";

type Listener = (e: EventEnvelope, rawType: string) => void;
type StateFn = (connected: boolean) => void;
export interface StreamChange { connected: boolean; accounts: readonly string[] | null }

const STALE_CHECK_MS = 5_000;

export function ssePoll(liveMs: number, offlineMs: number): () => number {
  return () => (eventBus.isConnected() ? liveMs : offlineMs);
}

interface Host {
  byType: Map<string, Set<Listener>>;
  emit(type: string, e: EventEnvelope): void;
  streamState(s: Stream, connected: boolean): void;
}

class Stream {
  state: BusState = initialBusState;
  es: EventSource | null = null;
  private staleCheckTimer: ReturnType<typeof setInterval> | null = null;
  private disposed = false;

  constructor(private host: Host, readonly cell: string | undefined, private clock: boolean, private savedCursor = "") {
    if (savedCursor) this.state = { ...initialBusState, lastEventId: savedCursor };
  }

  connected(): boolean {
    return isConnected(this.state, this.ready(), Date.now());
  }

  send(ev: BusInput) {
    if (!this.disposed) this.run(decide(this.state, ev));
  }

  dispose() {
    this.send({ type: "Pause" });
    this.disposed = true;
    if (this.staleCheckTimer) clearInterval(this.staleCheckTimer);
  }

  attach(type: string) {
    if (this.es && !NOT_NATIVE.has(type)) this.attachNativeListener(this.es, type);
  }

  private ready(): number | null {
    return this.es ? this.es.readyState : null;
  }

  private run({ state, effects }: Decision) {
    this.state = state;
    for (const fx of effects) this.perform(fx);
  }

  private perform(fx: BusEffect) {
    switch (fx.type) {
      case "Open":
        this.open(eventsUrl(fx.scope, resolveShareToken(), fx.lastEventId || this.savedCursor, this.cell), fx.gen);
        this.savedCursor = "";
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
        this.host.streamState(this, fx.connected);
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

    for (const type of this.host.byType.keys()) {
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
  // Cells: control's clock only, so the offset doesn't flip between Relays.
  private pingEvents(raw: string): Queued[] {
    const p = parse(raw);
    if (this.clock && typeof p.ts === "number" && Number.isFinite(p.ts)) {
      setRelayOffset(serverOffset(p.ts * 1000, Date.now()));
    }
    if (!this.host.byType.has("ping")) return [];
    const fresh = p.fresh;
    return fresh && typeof fresh === "object" && !Array.isArray(fresh) ? [["ping", p]] : [];
  }

  private applyAll(events: Queued[]) {
    if (!events.length) return;
    if (events.length === 1) {
      this.host.emit(events[0][0], events[0][1]);
      return;
    }
    notifyManager.batch(() => {
      for (const [t, e] of events) this.host.emit(t, e);
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
      if (typeof m?.type !== "string" || !this.host.byType.has(m.type)) continue;
      events.push([m.type, (m.data ?? {}) as EventEnvelope]);
    }
    return events;
  }
}

function pageProto(): Proto {
  if (typeof performance === "undefined" || typeof performance.getEntriesByType !== "function") return "unknown";
  const res = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
  const hop = res.findLast?.((e) => e.name.includes("/auth/cells"))?.nextHopProtocol
    || (performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined)?.nextHopProtocol;
  return protoOf(hop);
}

class EventBus implements Host {
  byType = new Map<string, Set<Listener>>();
  private streams = new Map<string, Stream>();
  private cursors = new Map<string, string>();
  private scope: Scope | null = null;
  private paused = false;
  private cells: CellBusState = INITIAL_CELL_BUS;
  private map: CellMap | null = null;
  private watching = false;
  private mapRetry: ReturnType<typeof setTimeout> | null = null;
  private mapLoad = INITIAL_MAP_LOAD;
  private stateListeners = new Set<{ fn: StateFn; account?: string }>();
  private streamListeners = new Set<(c: StreamChange) => void>();
  private blockedListeners = new Set<() => void>();

  isConnected(accountId?: string): boolean {
    const legacy = this.streams.get("");
    if (legacy) return legacy.connected();
    if (accountId !== undefined) return accountLive(this.cells, accountId) && this.streamOf(accountId)!.connected();
    return allLive(this.cells) && [...this.streams.values()].every((s) => s.connected());
  }

  onStateChange(fn: StateFn, accountId?: string): () => void {
    const entry = { fn, account: accountId };
    this.stateListeners.add(entry);
    try { fn(this.isConnected(accountId)); } catch { }
    return () => { this.stateListeners.delete(entry); };
  }

  onStreamState(fn: (c: StreamChange) => void): () => void {
    this.streamListeners.add(fn);
    return () => { this.streamListeners.delete(fn); };
  }

  liveBlocked = (): boolean => blocked(this.cells);

  onBlocked = (fn: () => void): (() => void) => {
    this.blockedListeners.add(fn);
    return () => { this.blockedListeners.delete(fn); };
  };

  setScope(scope: Scope) {
    this.scope = scope;
    if (!cellMode()) {
      this.legacy().send({ type: "SetScope", scope });
      return;
    }
    this.resetMapLoad();
    if (!this.watching) {
      this.watching = true;
      onCellMap(() => { if (currentCellMap() !== this.map) this.replan(); });
    }
    this.replan();
  }

  pause() {
    this.paused = true;
    for (const s of this.streams.values()) s.send({ type: "Pause" });
  }

  resume() {
    this.paused = false;
    for (const s of this.streams.values()) s.send({ type: "Resume" });
  }

  isPaused(): boolean {
    return this.paused;
  }

  on(type: string, fn: Listener): () => void {
    if (!this.byType.has(type)) {
      this.byType.set(type, new Set());
      for (const s of this.streams.values()) s.attach(type);
    }
    this.byType.get(type)!.add(fn);
    return () => {
      this.byType.get(type)?.delete(fn);
    };
  }

  emit(type: string, parsed: EventEnvelope) {
    const exact = this.byType.get(type);
    const wild = this.byType.get("*");
    if (exact) for (const fn of exact) safe(fn, parsed, type);
    if (wild) for (const fn of wild) safe(fn, parsed, type);
  }

  streamState(s: Stream, connected: boolean) {
    if (s.cell === undefined) {
      for (const { fn } of this.stateListeners) notify(fn, connected);
      for (const fn of this.streamListeners) safe2(fn, { connected, accounts: null });
      return;
    }
    const prev = this.cells;
    this.cells = cellBusReducer(prev, { type: "Live", cell: s.cell, live: connected });
    this.publish(prev);
  }

  private legacy(): Stream {
    let s = this.streams.get("");
    if (!s) {
      s = new Stream(this, undefined, true);
      this.streams.set("", s);
      if (this.paused) s.send({ type: "Pause" });
    }
    return s;
  }

  private streamOf(accountId: string): Stream | undefined {
    const p = this.cells.planned.find((x) => x.accounts.includes(accountId));
    return p && this.streams.get(p.cell);
  }

  private resetMapLoad() {
    if (this.mapRetry) clearTimeout(this.mapRetry);
    this.mapRetry = null;
    this.mapLoad = mapLoadReducer(this.mapLoad, "reset");
  }

  private replan() {
    if (!this.scope) return;
    const m = currentCellMap();
    if (!m) {
      if (this.mapLoad.phase !== "ready") return;
      const loading = this.mapLoad = mapLoadReducer(this.mapLoad, "start");
      void loadCellMap().catch((error: unknown) => {
        if (this.mapLoad !== loading) return;
        const denied = error instanceof RelayError && (error.status === 401 || error.status === 403);
        this.mapLoad = mapLoadReducer(loading, denied ? "denied" : "failed");
        if (this.mapLoad.phase !== "waiting") return;
        this.mapRetry = setTimeout(() => {
          this.mapRetry = null;
          this.mapLoad = mapLoadReducer(this.mapLoad, "retry");
          this.replan();
        }, this.mapLoad.delay);
      });
      return;
    }
    this.resetMapLoad();
    const sameGrant = this.map?.actor === m.actor && this.map.grant_gen === m.grant_gen;
    if (!sameGrant) this.cursors.clear();
    this.map = m;
    const prev = this.cells;
    this.cells = cellBusReducer(prev, { type: "Plan", map: m, scope: this.scope, proto: pageProto() });
    const diff = streamDiff(prev.planned, this.cells.planned);
    for (const cell of diff.close) {
      const stream = this.streams.get(cell);
      if (sameGrant && stream?.state.lastEventId) this.cursors.set(cell, stream.state.lastEventId);
      stream?.dispose();
      this.streams.delete(cell);
    }
    for (const p of diff.rescope) this.streams.get(p.cell)?.send({ type: "SetScope", scope: p.scope });
    for (const p of diff.open) {
      const s = new Stream(this, p.cell, p.cell === m.control, this.cursors.get(p.cell));
      this.cursors.delete(p.cell);
      this.streams.set(p.cell, s);
      if (this.paused) s.send({ type: "Pause" });
      s.send({ type: "SetScope", scope: p.scope });
    }
    this.publish(prev);
  }

  private publish(prev: CellBusState) {
    const next = this.cells;
    if (prev === next) return;
    if (blocked(prev) !== blocked(next)) for (const fn of this.blockedListeners) fn();
    setStreamGrey(downAccounts(next));
    const changes = liveChanges(prev, next);
    const was = allLive(prev);
    const now = allLive(next);
    for (const { fn, account } of this.stateListeners) {
      if (account === undefined) {
        if (was !== now) notify(fn, now);
        continue;
      }
      if (accountLive(prev, account) !== accountLive(next, account)) notify(fn, accountLive(next, account));
    }
    for (const c of changes) for (const fn of this.streamListeners) safe2(fn, { connected: c.live, accounts: c.accounts });
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

function safe2(fn: (c: StreamChange) => void, c: StreamChange) {
  try { fn(c); } catch (err) { console.error("[events] stream listener error", err); }
}

function notify(fn: StateFn, connected: boolean) {
  try { fn(connected); } catch (err) { console.error("[events] state listener error", err); }
}

export const eventBus = new EventBus();
