import { APP_OPEN_WARM_FALLBACK_MS, type TabLease } from "@/lib/viewLease";

export type ReadGate = "off" | "once" | "live";

export const REFRESH_OLDER_MS = 30_000;
export const FALLBACK_QUIET_MS = 20_000;
export const FALLBACK_MAX_MS = 300_000;

export function fallbackDeadline(loadedAt: number, lastArmAt: number): number {
  return Math.min(loadedAt + FALLBACK_MAX_MS,
    Math.max(loadedAt + APP_OPEN_WARM_FALLBACK_MS, lastArmAt + FALLBACK_QUIET_MS));
}

// Unleased Creators have no interval or focus refetch: off until armed, then once (refetch only when invalidated).
export function readGate(o: { leased: boolean; armed: boolean }): ReadGate {
  return o.leased ? "live" : o.armed ? "once" : "off";
}

export function onScreenGate(gate: ReadGate): ReadGate {
  return gate === "off" ? "once" : gate;
}

export function gateOptions(gate: ReadGate): {
  enabled?: false; staleTime?: number; refetchInterval?: false; refetchOnWindowFocus?: false;
} {
  if (gate === "off") return { enabled: false };
  // eslint-disable-next-line local/no-fixed-polling -- `false` turns the reader's own poll off, it adds none
  if (gate === "once") return { staleTime: Infinity, refetchInterval: false, refetchOnWindowFocus: false };
  return {};
}

export function gainedOf(prev: TabLease, next: TabLease): string[] {
  const out = [...next.leased].filter((a) => !prev.leased.has(a));
  if (next.selected && next.selected !== prev.selected && !out.includes(next.selected)) out.push(next.selected);
  return out;
}

export function wantsRefresh(dataUpdatedAt: number, now: number): boolean {
  return now - dataUpdatedAt > REFRESH_OLDER_MS;
}


const armed = new Set<string>();
let fallbackDue = false;
let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
let lastArmAt = 0;
let loadedAt = typeof performance !== "undefined" && performance.timeOrigin ? performance.timeOrigin : Date.now();
let version = 0;
const listeners = new Set<() => void>();

function bump(): void {
  version += 1;
  for (const fn of listeners) fn();
}

export function armRead(accountId: string | undefined | null): void {
  if (!accountId || armed.has(accountId)) return;
  armed.add(accountId);
  lastArmAt = Date.now();
  bump();
}

export function isArmed(accountId: string): boolean {
  return fallbackDue || armed.has(accountId);
}

export function armedVersion(): number {
  return version;
}

export function onArmed(fn: () => void): () => void {
  listeners.add(fn);
  if (!fallbackDue && fallbackTimer === null) startFallbackTimer();
  return () => { listeners.delete(fn); };
}

function startFallbackTimer(): void {
  const wait = Math.min(FALLBACK_MAX_MS, Math.max(0, fallbackDeadline(loadedAt, lastArmAt) - Date.now()));
  fallbackTimer = setTimeout(() => {
    if (Date.now() < fallbackDeadline(loadedAt, lastArmAt)) return startFallbackTimer();
    fallbackDue = true;
    bump();
  }, wait);
}

export function resetReadGate(at: number = Date.now()): void {
  armed.clear();
  fallbackDue = false;
  if (fallbackTimer !== null) clearTimeout(fallbackTimer);
  fallbackTimer = null;
  lastArmAt = 0;
  loadedAt = at;
  version += 1;
}
