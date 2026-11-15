/**
 * When the money rail, the bell and the count readers (useOfNotifCount, OF Manager's Creator column) may read a
 * Creator's OnlyFans money lists and notifications count (ADR-0031, phase-01 1b; hooks/useOfReadGate.ts applies it).
 *
 * A Creator this tab leases (lib/viewLease `tabLease`) reads as today: `live`. An unleased one has no safety interval
 * and no focus refetch: it is `off` until armed, then `once` (enabled, never stale by age, so it refetches only when
 * invalidated: its next `creator_warmed`). It is armed, for the rest of the document load, by its `creator_warmed`
 * (useAccountStateEvents), by this tab leasing it, or by APP_OPEN_WARM_FALLBACK_MS after the load (no warm result
 * came). On a lease gain or a selection, its queries older than REFRESH_OLDER_MS refetch at once (`gainedOf`).
 * Dead-session Creators are not in any reader's targets (each reader drops them itself), so nothing reads them.
 */

import { APP_OPEN_WARM_FALLBACK_MS, type TabLease } from "@/lib/viewLease";

export type ReadGate = "off" | "once" | "live";

/** A lease gain or a selection refetches a query older than this. */
export const REFRESH_OLDER_MS = 30_000;

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
  if (!fallbackDue && fallbackTimer === null) {
    fallbackTimer = setTimeout(() => {
      fallbackDue = true;
      bump();
    }, Math.min(APP_OPEN_WARM_FALLBACK_MS, Math.max(0, loadedAt + APP_OPEN_WARM_FALLBACK_MS - Date.now())));
  }
  return () => { listeners.delete(fn); };
}

/** Tests: a fresh document load at `at` (nothing armed, the deadline not started). */
export function resetReadGate(at: number = Date.now()): void {
  armed.clear();
  fallbackDue = false;
  if (fallbackTimer !== null) clearTimeout(fallbackTimer);
  fallbackTimer = null;
  loadedAt = at;
  version += 1;
}
