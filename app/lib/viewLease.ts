/**
 * The View lease client (ADR-0031, phase-01): this tab's id, the front Knobs, the renewal post
 * (`POST /admin/view-lease`, the session cookie, no X-Account-Id) and the lease sources' registry (`holdLease`,
 * `useViewLease`'s core). The state is `viewLeaseState`; the one poster is ViewLeaseHeartbeat (root layout, inside the
 * auth gate), which listens to the registry (`onLeaseHolds`).
 */

import { relay } from "@/lib/relay";
import { sortedIds, type LeaseBody } from "@/lib/viewLeaseState";

/** A tab renews its lease this often (the Relay's VIEW_LEASE_TTL_S is 60 s). */
export const VIEW_LEASE_RENEW_MS = 20_000;
/** The opening post waits for the event stream at most this long. */
export const OPENED_WAIT_MS = 5_000;

const TAB_KEY = "chatterly:view-lease-tab";
let memoTab: string | null = null;

function randomId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

/** This tab's id: random, kept in sessionStorage (one per tab; a reload keeps it). */
export function tabId(): string {
  if (memoTab) return memoTab;
  try {
    const saved = window.sessionStorage.getItem(TAB_KEY);
    memoTab = saved || randomId();
    if (!saved) window.sessionStorage.setItem(TAB_KEY, memoTab);
  } catch {
    memoTab = randomId();
  }
  return memoTab;
}

export interface LeaseAnswer {
  leased: string[];
  ttl_s: number;
  warm: "started" | "reused" | "none";
}

export function postLease(body: LeaseBody): Promise<LeaseAnswer> {
  return relay.post<LeaseAnswer>("/admin/view-lease", body);
}

// ── Lease sources: what is on screen, one hold per key ───────────────────────────────────────────────────────────

const holds = new Map<string, readonly string[]>();
const holdListeners = new Set<(key: string, accountIds: string[]) => void>();

function tell(key: string, ids: readonly string[]): void {
  for (const fn of holdListeners) fn(key, [...ids]);
}

/** Lease `accountIds` under `key` until the returned release is called. A key is one holder (`useViewLease`: its
 *  label and the component's `useId`, e.g. "strip#:r1:"); a second hold on a key replaces its set, the release drops
 *  it, and a replaced hold's release is a no-op. */
export function holdLease(key: string, accountIds: readonly string[]): () => void {
  const ids = sortedIds(accountIds);
  holds.set(key, ids);
  tell(key, ids);
  return () => {
    if (holds.get(key) !== ids) return;
    holds.delete(key);
    tell(key, []);
  };
}

/** Called with (key, its Creators) on every change ([] = released), and at once for every hold live now. Returns the
 *  unsubscribe. The heartbeat dispatches Hold / Release from it. */
export function onLeaseHolds(fn: (key: string, accountIds: string[]) => void): () => void {
  holdListeners.add(fn);
  for (const [key, ids] of holds) fn(key, [...ids]);
  return () => { holdListeners.delete(fn); };
}
