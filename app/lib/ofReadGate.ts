/**
 * When the money rail, the bell and the count readers (useOfNotifCount, OF Manager's Creator column) may read a
 * Creator's OnlyFans money lists and notifications count (ADR-0031, phase-01 1b; hooks/useOfReadGate.ts applies it).
 *
 * A Creator this tab leases (lib/viewLease `tabLease`) reads as today: `live`. An unleased one has no safety interval
 * and no focus refetch: it is `off` until armed, then `once` (enabled, never stale by age, so it refetches only when
 * invalidated: its next `creator_warmed`). It is armed, for the rest of the document load, by its `creator_warmed`
 * (useAccountStateEvents), by this tab leasing it, or by the fallback deadline (no warm result came):
 * APP_OPEN_WARM_FALLBACK_MS after the load, pushed to FALLBACK_QUIET_MS after the last arm while the warm is still
 * landing, never past FALLBACK_MAX_MS (`fallbackDeadline`). On a lease gain or a selection, its queries older than REFRESH_OLDER_MS refetch at once (`gainedOf`).
 * Dead-session Creators are not in any reader's targets (each reader drops them itself), so nothing reads them.
 */

import { APP_OPEN_WARM_FALLBACK_MS, type TabLease } from "@/lib/viewLease";

export type ReadGate = "off" | "once" | "live";

/** A lease gain or a selection refetches a query older than this. */
export const REFRESH_OLDER_MS = 30_000;
/** The fallback waits this long after the last arm (the warm still landing: its queued Creators are read in turn on
 *  their exit, not all at once by the tab)... */
export const FALLBACK_QUIET_MS = 20_000;
/** ...but never longer than this after the load. */
export const FALLBACK_MAX_MS = 300_000;

/** When every unarmed Creator arms (epoch ms): APP_OPEN_WARM_FALLBACK_MS after the load, or FALLBACK_QUIET_MS after
 *  the last arm if later, capped at FALLBACK_MAX_MS after the load. */
export function fallbackDeadline(loadedAt: number, lastArmAt: number): number {
  return Math.min(loadedAt + FALLBACK_MAX_MS,
    Math.max(loadedAt + APP_OPEN_WARM_FALLBACK_MS, lastArmAt + FALLBACK_QUIET_MS));
}

export function readGate(o: { leased: boolean; armed: boolean }): ReadGate {
  return o.leased ? "live" : o.armed ? "once" : "off";
}

/** The query options a gate overrides: `off` disabled; `once` no interval, no focus refetch, never stale by age;
 *  `live` the reader's own. */
export function gateOptions(gate: ReadGate): {
  enabled?: false; staleTime?: number; refetchInterval?: false; refetchOnWindowFocus?: false;
} {
  if (gate === "off") return { enabled: false };
  // eslint-disable-next-line local/no-fixed-polling -- `false` turns the reader's own poll off, it adds none
  if (gate === "once") return { staleTime: Infinity, refetchInterval: false, refetchOnWindowFocus: false };
  return {};
}

/** The Creators that refetch their stale queries now: those `next` leases and `prev` did not, and a newly selected
 *  one (even if it was leased already). */
export function gainedOf(prev: TabLease, next: TabLease): string[] {
  const out = [...next.leased].filter((a) => !prev.leased.has(a));
  if (next.selected && next.selected !== prev.selected && !out.includes(next.selected)) out.push(next.selected);
  return out;
}

/** A query last updated at `dataUpdatedAt` (0: never) wants the gain refetch at `now`. */
export function wantsRefresh(dataUpdatedAt: number, now: number): boolean {
  return now - dataUpdatedAt > REFRESH_OLDER_MS;
}

// ── Armed Creators, per document load ──────────────────────────────────────────────────────────────────────────

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

/** Arm `accountId` for the rest of the document load. */
export function armRead(accountId: string | undefined | null): void {
  if (!accountId || armed.has(accountId)) return;
  armed.add(accountId);
  lastArmAt = Date.now();
  bump();
}

export function isArmed(accountId: string): boolean {
  return fallbackDue || armed.has(accountId);
}

/** Changes on every arm and at the fallback deadline (useSyncExternalStore's snapshot). */
export function armedVersion(): number {
  return version;
}

/** useSyncExternalStore's subscribe; the first one starts the fallback deadline's timer. */
export function onArmed(fn: () => void): () => void {
  listeners.add(fn);
  if (!fallbackDue && fallbackTimer === null) startFallbackTimer();
  return () => { listeners.delete(fn); };
}

/** Waits for the fallback deadline, re-read when the timer fires (an arm since may have pushed it). */
function startFallbackTimer(): void {
  const wait = Math.min(FALLBACK_MAX_MS, Math.max(0, fallbackDeadline(loadedAt, lastArmAt) - Date.now()));
  fallbackTimer = setTimeout(() => {
    if (Date.now() < fallbackDeadline(loadedAt, lastArmAt)) return startFallbackTimer();
    fallbackDue = true;
    bump();
  }, wait);
}

/** Tests: a fresh document load at `at` (nothing armed, the deadline not started). */
export function resetReadGate(at: number = Date.now()): void {
  armed.clear();
  fallbackDue = false;
  if (fallbackTimer !== null) clearTimeout(fallbackTimer);
  fallbackTimer = null;
  lastArmAt = 0;
  loadedAt = at;
  version += 1;
}
