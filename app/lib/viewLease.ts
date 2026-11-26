import { cellMode, relay } from "@/lib/relay";
import { SELECTED_SOURCE, sortedIds, type LeaseBody } from "@/lib/viewLeaseState";

export const VIEW_LEASE_RENEW_MS = 20_000;
export const OPENED_WAIT_MS = 5_000;
export const APP_OPEN_WARM_FALLBACK_MS = 90_000;

let memoTab: string | null = null;

function randomId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

// In memory, not sessionStorage: a popout or Duplicate tab copies it and two windows on one id would replace each other's set.
export function tabId(): string {
  memoTab ??= randomId();
  return memoTab;
}

export interface LeaseAnswer {
  leased: string[];
  ttl_s: number;
  warm: "started" | "reused" | "none";
}

export async function postLease(body: LeaseBody): Promise<LeaseAnswer> {
  if (!cellMode()) return relay.post<LeaseAnswer>("/admin/view-lease", body);
  const ids = [...new Set([...body.account_ids, ...(body.selected ? [body.selected] : [])])];
  const answers = await Promise.all(ids.map((accountId) => relay.post<LeaseAnswer>("/admin/view-lease", body, { accountId })));
  const warms = answers.map((a) => a.warm);
  return {
    leased: [...new Set(answers.flatMap((a) => a.leased))],
    ttl_s: answers[0]?.ttl_s ?? 0,
    warm: warms.includes("started") ? "started" : warms.includes("reused") ? "reused" : "none",
  };
}


const holds = new Map<string, readonly string[]>();
const holdListeners = new Set<(key: string, accountIds: string[]) => void>();

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

export function tabLease(): TabLease {
  return tabSnap;
}

export function onTabLease(fn: () => void): () => void {
  const l = () => fn();
  holdListeners.add(l);
  return () => { holdListeners.delete(l); };
}

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

export function onLeaseHolds(fn: (key: string, accountIds: string[]) => void): () => void {
  holdListeners.add(fn);
  for (const [key, ids] of holds) fn(key, [...ids]);
  return () => { holdListeners.delete(fn); };
}
