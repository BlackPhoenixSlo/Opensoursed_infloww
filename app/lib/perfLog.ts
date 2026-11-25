"use client";


export type PerfPhase = "requested" | "delivered" | "painted" | "later" | "error" | "open";

export interface PerfEvent {
  opId: string;
  kind: string;
  phase: PerfPhase;
  ts: number;
  tabId?: string;
  meta?: Record<string, unknown>;
}

export interface PerfTabContext {
  tabId: string;
  parentTabId: string | null;
  tabOpenedAt: number;
  isRootTab: boolean;
}

const BUFFER_MAX = 500;
const buffer: PerfEvent[] = [];
const subs = new Set<(e: PerfEvent) => void>();
const firstSeenByOp = new Map<string, number>();
const lastSeenByOp = new Map<string, number>();


const TAB_ID_KEY = "chatterly:perf-tab-id";
const TAB_OPENED_KEY = "chatterly:perf-tab-opened-at";
const PARENT_TAB_ID_KEY = "chatterly:perf-parent-tab-id";

function readSession(k: string): string | null {
  if (typeof window === "undefined") return null;
  try { return window.sessionStorage.getItem(k); } catch { return null; }
}

function writeSession(k: string, v: string): void {
  if (typeof window === "undefined") return;
  try { window.sessionStorage.setItem(k, v); } catch { }
}

function discoverParentTabId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const op = window.opener as (Window & { __perfTabId?: string }) | null;
    if (op && op !== window) {
      const id = op.__perfTabId;
      if (typeof id === "string" && id.length > 0) return id;
    }
  } catch { }
  return null;
}

function bootTabContext(): PerfTabContext {
  if (typeof window === "undefined") {
    return { tabId: "ssr", parentTabId: null, tabOpenedAt: 0, isRootTab: true };
  }
  let tabId = readSession(TAB_ID_KEY);
  let openedRaw = readSession(TAB_OPENED_KEY);
  if (!tabId) {
    tabId = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `t-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    writeSession(TAB_ID_KEY, tabId);
  }
  if (!openedRaw) {
    openedRaw = String(Date.now());
    writeSession(TAB_OPENED_KEY, openedRaw);
  }
  let parentTabId = readSession(PARENT_TAB_ID_KEY);
  if (!parentTabId) {
    parentTabId = discoverParentTabId();
    if (parentTabId) writeSession(PARENT_TAB_ID_KEY, parentTabId);
  }
  (window as Window & { __perfTabId?: string }).__perfTabId = tabId;
  return {
    tabId,
    parentTabId,
    tabOpenedAt: Number(openedRaw) || Date.now(),
    isRootTab: !parentTabId,
  };
}

const TAB_CTX: PerfTabContext = bootTabContext();

function shortTab(id: string): string {
  return id === "ssr" ? "ssr" : id.slice(0, 6);
}


function emit(evt: PerfEvent): void {
  if (evt.tabId == null) evt.tabId = TAB_CTX.tabId;
  buffer.push(evt);
  if (buffer.length > BUFFER_MAX) buffer.splice(0, buffer.length - BUFFER_MAX);

  const first = firstSeenByOp.get(evt.opId);
  const last = lastSeenByOp.get(evt.opId);
  if (first == null) firstSeenByOp.set(evt.opId, evt.ts);
  lastSeenByOp.set(evt.opId, evt.ts);

  const totalMs = first != null ? evt.ts - first : 0;
  const stepMs = last != null ? evt.ts - last : 0;

  if (typeof window !== "undefined") {
    // eslint-disable-next-line no-console
    console.info(
      `[perf] ${evt.kind} ${evt.phase} +${stepMs}ms Σ${totalMs}ms id=${evt.opId} tab=${shortTab(evt.tabId)}`,
      evt.meta ?? {},
    );
  }
  for (const s of subs) {
    try { s(evt); } catch { }
  }
  queueForIngest(evt);
}

function nowMs(): number {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    const origin = (performance as Performance & { timeOrigin?: number }).timeOrigin;
    if (typeof origin === "number") return origin + performance.now();
  }
  return Date.now();
}

let opCounter = 0;
export function perfOpId(scope: string): string {
  opCounter += 1;
  return `${scope}:${opCounter}:${Math.random().toString(36).slice(2, 6)}`;
}

export function perfLog(
  opId: string,
  kind: string,
  phase: PerfPhase,
  meta?: Record<string, unknown>,
): void {
  emit({ opId, kind, phase, ts: nowMs(), meta });
}

export function perfDelivered(opId: string, kind: string, meta?: Record<string, unknown>): void {
  perfLog(opId, kind, "delivered", meta);
}

export function perfPainted(opId: string, kind: string, meta?: Record<string, unknown>): void {
  perfLog(opId, kind, "painted", meta);
}

export function perfError(opId: string, kind: string, meta?: Record<string, unknown>): void {
  perfLog(opId, kind, "error", meta);
}


const PAINT_PENDING_MAX = 200;
const pendingPaint = new Map<string, { opId: string; painted: boolean }>();

export function perfPaintPending(key: string, opId: string): void {
  if (pendingPaint.size >= PAINT_PENDING_MAX) {
    const oldest = pendingPaint.keys().next();
    if (!oldest.done) pendingPaint.delete(oldest.value);
  }
  pendingPaint.set(key, { opId, painted: false });
}

export function perfPaintOnce(
  key: string,
  kind: string,
  meta?: Record<string, unknown>,
): void {
  const entry = pendingPaint.get(key);
  if (!entry || entry.painted) return;
  entry.painted = true;
  perfPainted(entry.opId, kind, meta);
}

export function perfSnapshot(): PerfEvent[] {
  return buffer.slice();
}

export function perfLogSubscribe(fn: (e: PerfEvent) => void): () => void {
  subs.add(fn);
  return () => { subs.delete(fn); };
}

export function perfTabContext(): PerfTabContext {
  return { ...TAB_CTX };
}

export function perfBoot(): void {
}


const INGEST_URL = "/admin/perflog/ingest";
const FLUSH_INTERVAL_MS = 10_000;
const FLUSH_MAX = 50;
const pendingForIngest: PerfEvent[] = [];
let flushTimer: ReturnType<typeof setInterval> | null = null;
const ingestDisabled =
  typeof window !== "undefined" &&
  Boolean((window as Window & { __perfLogNoIngest?: boolean }).__perfLogNoIngest);

function buildIngestBody(events: PerfEvent[]): string {
  return JSON.stringify({
    tabId: TAB_CTX.tabId,
    parentTabId: TAB_CTX.parentTabId,
    events: events.map((e) => ({
      opId: e.opId,
      kind: e.kind,
      phase: e.phase,
      ts: e.ts,
      tabId: e.tabId ?? TAB_CTX.tabId,
      meta: e.meta,
    })),
  });
}

function flushNow(useBeacon = false): void {
  if (ingestDisabled) {
    pendingForIngest.length = 0;
    return;
  }
  if (pendingForIngest.length === 0) return;
  // splice, not slice: a racing unload beacon must never double-send.
  const batch = pendingForIngest.splice(0);
  const body = buildIngestBody(batch);
  try {
    if (useBeacon && typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([body], { type: "application/json" });
      const ok = navigator.sendBeacon(INGEST_URL, blob);
      if (ok) return;
    }
    if (typeof fetch !== "function") return;
    void fetch(INGEST_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      keepalive: true,
      credentials: "same-origin",
    }).catch(() => { });
  } catch { }
}

function queueForIngest(evt: PerfEvent): void {
  if (ingestDisabled) return;
  pendingForIngest.push(evt);
  if (pendingForIngest.length >= FLUSH_MAX) {
    queueMicrotask(() => flushNow(false));
  }
}


if (typeof window !== "undefined" && TAB_CTX.tabId !== "ssr") {
  Object.defineProperty(window, "__perfLog", {
    configurable: true,
    get: () => perfSnapshot(),
  });
  Object.defineProperty(window, "__perfTabCtx", {
    configurable: true,
    get: () => perfTabContext(),
  });

  let navMeta: Record<string, unknown> = {};
  try {
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    if (nav) {
      navMeta = {
        navType: nav.type,
        domContentLoadedMs: Math.round(nav.domContentLoadedEventEnd),
        loadEventEndMs: Math.round(nav.loadEventEnd),
        responseEndMs: Math.round(nav.responseEnd),
      };
    }
  } catch { }

  emit({
    opId: TAB_CTX.tabId,
    kind: "tab",
    phase: "open",
    ts: TAB_CTX.tabOpenedAt,
    tabId: TAB_CTX.tabId,
    meta: {
      tabId: TAB_CTX.tabId,
      parentTabId: TAB_CTX.parentTabId,
      isRootTab: TAB_CTX.isRootTab,
      route: window.location.pathname + window.location.search,
      referrer: document.referrer || null,
      ...navMeta,
    },
  });

  if (flushTimer == null) {
    flushTimer = setInterval(() => flushNow(false), FLUSH_INTERVAL_MS);
  }

  window.addEventListener("pagehide", () => flushNow(true), { capture: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushNow(true);
  }, { capture: true });
}
