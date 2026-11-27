import { cellMode } from "@/lib/cellFlag";
import { groupByCell, type CellMap } from "@/lib/cellInbox";
import { loadCellMap } from "@/lib/cellMap";
import { relay } from "@/lib/relay";
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

interface CellLeaseState {
  opening: boolean;
  opened: Set<string>;
  held: Set<string>;
  flight?: Promise<LeaseAnswer>;
}

const cellLeases = new Map<string, CellLeaseState>();

export async function postLease(body: LeaseBody): Promise<LeaseAnswer> {
  if (!cellMode()) return relay.post<LeaseAnswer>("/admin/view-lease", body);
  const map = await loadCellMap();
  const key = JSON.stringify([map.actor, body.tab]);
  let state = cellLeases.get(key);
  if (!state) {
    state = { opening: false, opened: new Set(), held: new Set() };
    cellLeases.set(key, state);
  }
  const previous = state.flight;
  const pending = previous
    ? previous.catch(() => {}).then(() => postCellLease(body, state, map))
    : postCellLease(body, state, map);
  state.flight = pending;
  try {
    return await pending;
  } finally {
    if (state.flight === pending) delete state.flight;
  }
}

async function postCellLease(body: LeaseBody, state: CellLeaseState, map: CellMap): Promise<LeaseAnswer> {
  state.opening ||= body.opened;
  const held = new Set(body.account_ids);
  const ids = [...held, ...(body.selected && !held.has(body.selected) ? [body.selected] : [])];
  const groups = new Map(groupByCell(ids, map));
  const granted = new Set(map.accounts.map((a) => a.cell));
  const cells = new Set([
    ...[...granted].filter((cell) => state.opening && !state.opened.has(cell)),
    ...groups.keys(), ...state.held,
  ]);
  const settled = await Promise.allSettled([...cells].map(async (cellId) => {
    const accounts = groups.get(cellId) ?? [];
    const opened = state.opening && granted.has(cellId) && !state.opened.has(cellId);
    if (accounts.length) state.held.add(cellId);
    const answer = await relay.post<LeaseAnswer>("/admin/view-lease", {
      ...body, opened, account_ids: accounts.filter((id) => held.has(id)),
      selected: body.selected && accounts.includes(body.selected) ? body.selected : null,
    }, { cellId }, AbortSignal.timeout(5_000));
    if (opened) state.opened.add(cellId);
    if (!accounts.length) state.held.delete(cellId);
    return answer;
  }));
  const answers = settled.flatMap((r) => r.status === "fulfilled" ? [r.value] : []);
  const failure = settled.find((r) => r.status === "rejected");
  if (!answers.length && failure) throw failure.reason;
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
