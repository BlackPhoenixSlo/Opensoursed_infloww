/**
 * The View lease client (ADR-0031, phase-01): this tab's id, the front Knobs, the renewal post
 * (`POST /admin/view-lease`, the session cookie, no X-Account-Id) and the lease sources' registry (`holdLease`,
 * `useViewLease`'s core; the heartbeat holds the selected Creator under SELECTED_SOURCE). The state is
 * `viewLeaseState`; the one poster is ViewLeaseHeartbeat (root layout, inside the auth gate), which listens to the
 * registry (`onLeaseHolds`). `tabLease` is the registry's union, for the readers that gate on it.
 */

import { relay } from "@/lib/relay";
import { SELECTED_SOURCE, sortedIds, type LeaseBody } from "@/lib/viewLeaseState";

/** A tab renews its lease this often (the Relay's VIEW_LEASE_TTL_S is 60 s). */
export const VIEW_LEASE_RENEW_MS = 20_000;
/** The opening post waits for the event stream at most this long. */
export const OPENED_WAIT_MS = 5_000;
/** The rail's self-read deadline: this long after the document load, an unleased Creator whose `creator_warmed` never
 *  came reads its money lists and count itself (lib/ofReadGate.ts). */
export const APP_OPEN_WARM_FALLBACK_MS = 90_000;

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

/** What this tab leases now: every hold's Creators, and the selected one (the SELECTED_SOURCE hold, which
 *  ViewLeaseHeartbeat keeps). The count and money-list readers gate on it (hooks/useOfReadGate.ts). */
export interface TabLease {
  leased: ReadonlySet<string>;
  selected: string | null;
}
export const NO_TAB_LEASE: TabLease = { leased: new Set(), selected: null };
let tabSnap: TabLease = NO_TAB_LEASE;

function tell(key: string, ids: readonly string[]): void {
  tabSnap = { leased: new Set([...holds.values()].flat()), selected: holds.get(SELECTED_SOURCE)?.[0] ?? null };
  for (const fn of holdListeners) fn(key, [...ids]);
}

/** This tab's lease now; the same object until a hold changes (useSyncExternalStore's snapshot). */
export function tabLease(): TabLease {
  return tabSnap;
}

/** `fn` on every hold change; returns the unsubscribe (useSyncExternalStore's subscribe). */
export function onTabLease(fn: () => void): () => void {
  const l = () => fn();
  holdListeners.add(l);
  return () => { holdListeners.delete(l); };
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
