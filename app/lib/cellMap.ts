"use client";

import { useEffect, useSyncExternalStore } from "react";

import { cellMode } from "@/lib/cellFlag";
import type { ListCaller } from "@/hooks/chatListLoadMore";
import { relay, STALE_CELL_GEN_EVENT } from "@/lib/relay";
import {
  CELL_DEADLINE_MS, CELL_PAINT_MS, cellsReducer, cellToken, greyAccounts, groupByCell, INITIAL_CELLS, type Action,
  type CellMap, type CellsState,
} from "@/lib/cellInbox";

// Never persisted: a revoke bumps grant_gen, and a stale copy would key the inbox to the pre-revoke cache.
let map: CellMap | null = null;
let flight: Promise<CellMap> | null = null;
const REFRESH_INTERVAL_MS = 1_000;
let refreshAfter = -Infinity;
let staleBypassUsed = false;
type Source = "inbox" | "roster" | "seed";
const initialSources: Record<Source, CellsState> = { inbox: INITIAL_CELLS, roster: INITIAL_CELLS, seed: INITIAL_CELLS };
let sources = { ...initialSources };

function refreshOnStale(event: Event) {
  const reason = (event as CustomEvent).detail?.reason;
  if (reason) void refreshCellMap(reason === "stale").catch(() => {});
}
let grey: ReadonlySet<string> = new Set();
let mapGrey: readonly string[] = [];
let streamGrey: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();
const emit = () => { for (const l of listeners) l(); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
export const onCellMap = subscribe;

export function loadCellMap(): Promise<CellMap> {
  if (map) return Promise.resolve(map);
  return refreshCellMap();
}

export function refreshCellMap(stale = false): Promise<CellMap> {
  if (typeof window !== "undefined") window.addEventListener(STALE_CELL_GEN_EVENT, refreshOnStale);
  if (flight) return flight;
  const delay = refreshAfter - Date.now();
  const bypass = delay > 0 && stale && !staleBypassUsed;
  const read = () => relay.get<CellMap>("/auth/cells", undefined, AbortSignal.timeout(CELL_PAINT_MS));
  const start = () => {
    refreshAfter = Date.now() + REFRESH_INTERVAL_MS;
    staleBypassUsed = bypass;
    return read();
  };
  const response = delay > 0 && !bypass
    ? new Promise<void>((resolve) => setTimeout(resolve, delay)).then(() => {
      if (flight !== pending) throw new DOMException("Cell map forgotten", "AbortError");
      return start();
    })
    : start();
  const pending = response.then((m) => {
    if (flight !== pending) return m;
    if (!Array.isArray(m.accounts) || !Array.isArray(m.cells)) throw new Error("Invalid Cell map");
    if (!map || cellToken(map) !== cellToken(m)) {
      sources = { ...initialSources };
      map = m;
    }
    mapGrey = [];
    regrey();
    flight = null;
    emit();
    return map;
  }).catch((e: unknown) => {
    if (flight !== pending) throw e;
    flight = null;
    mapGrey = map?.accounts.map((a) => a.account_id) ?? [];
    if (regrey()) emit();
    throw e;
  });
  return flight = pending;
}

export function currentCellMap(): CellMap | null {
  return map;
}

export function forgetCellMap(): void {
  map = null;
  flight = null;
  refreshAfter = -Infinity;
  staleBypassUsed = false;
  if (typeof window !== "undefined") window.removeEventListener(STALE_CELL_GEN_EVENT, refreshOnStale);
  sources = { ...initialSources };
  grey = new Set();
  streamGrey = new Set();
  mapGrey = [];
  bundleFlights.clear();
  emit();
}

export function useCellMap(): CellMap | null {
  const m = useSyncExternalStore(subscribe, () => map, () => null);
  useEffect(() => {
    if (cellMode() && !map) loadCellMap().catch(() => {});
  }, []);
  return m;
}

export function cellScopeToken(): string | null {
  return map ? cellToken(map) : null;
}

function regrey(): boolean {
  const answered = new Set(Object.values(sources.inbox.cells).flatMap((cell) => cell.outcome === "ok" ? cell.accounts : []));
  const fallbackGrey = [...greyAccounts(sources.roster), ...greyAccounts(sources.seed)].filter((id) => !answered.has(id));
  const g = new Set([...greyAccounts(sources.inbox), ...fallbackGrey, ...streamGrey, ...mapGrey]);
  if (g.size === grey.size && [...g].every((id) => grey.has(id))) return false;
  grey = g;
  return true;
}

function dispatch(a: Action, source: Source): void {
  if (map && a.scope !== cellToken(map)) return;
  const prev = sources[source];
  const next = cellsReducer(prev, a);
  if (next === prev) return;
  sources[source] = next;
  if (regrey()) emit();
}

export function setStreamGrey(ids: ReadonlySet<string>): void {
  streamGrey = ids;
  if (regrey()) emit();
}

export function useGreyAccounts(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, () => grey, () => grey);
}

const bundleFlights = new Map<string, Promise<unknown>>();

export interface CellJob {
  cell: string;
  accounts: string[];
  signal: AbortSignal;
}

export type CellResult<T> =
  | { cell: string; accounts: string[]; ok: true; value: T; partial: string[] }
  | { cell: string; accounts: string[]; ok: false };

export async function askCells<T>(
  m: CellMap, accounts: readonly string[], outer: AbortSignal | undefined,
  run: (job: CellJob) => Promise<{ value: T; partial: string[] }>,
  { source = "inbox", greyAfterMs, onLate }: {
    source?: Source; greyAfterMs?: number; onLate?: (results: CellResult<T>[]) => void;
  } = {},
): Promise<CellResult<T>[]> {
  const scope = cellToken(m);
  const groups = groupByCell(accounts, m);
  const settled = new Map<string, CellResult<T>>();
  const all = Promise.all(groups.map(async ([cell, ids]) => {
    dispatch({ type: "ask", scope, cell, accounts: ids }, source);
    const timer = AbortSignal.timeout(CELL_PAINT_MS);
    const signal = outer ? AbortSignal.any([outer, timer]) : timer;
    let result: CellResult<T>;
    try {
      const { value, partial } = await run({ cell, accounts: ids, signal });
      dispatch({ type: "answered", scope, cell, partial }, source);
      result = { cell, accounts: ids, ok: true, value, partial };
    } catch (e) {
      if (outer?.aborted) throw e;
      dispatch({ type: timer.aborted || (e as Error)?.name === "TimeoutError" ? "timedOut" : "failed", scope, cell }, source);
      result = { cell, accounts: ids, ok: false };
    }
    settled.set(cell, result);
    return result;
  }));
  if (greyAfterMs === undefined) return all;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([all, new Promise<CellResult<T>[]>((resolve) => {
      timer = setTimeout(() => {
        for (const [cell] of groups) if (!settled.has(cell)) dispatch({ type: "timedOut", scope, cell }, source);
        void all.then(onLate, () => {});
        resolve(groups.flatMap(([cell]) => settled.get(cell) ?? []));
      }, greyAfterMs);
    })]);
  } finally {
    clearTimeout(timer);
  }
}

export function cellBundle(m: CellMap, cell: string, accounts: readonly string[], cursor: number, signal: AbortSignal,
  caller?: ListCaller): Promise<unknown> {
  const key = `${cellToken(m)}|${cell}|${cursor}|${accounts.join(",")}`;
  let f = bundleFlights.get(key);
  if (!f) {
    const qs = new URLSearchParams({ cursor: String(cursor), accounts: accounts.join(","), deadline_ms: String(CELL_DEADLINE_MS) });
    f = relay.get(`/admin/screens/inbox?${qs}`, { cellId: cell, ...(caller ? { caller } : {}) }, AbortSignal.timeout(CELL_PAINT_MS))
      .finally(() => bundleFlights.delete(key));
    bundleFlights.set(key, f);
  }
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason);
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    f.then(resolve, reject);
  });
}
