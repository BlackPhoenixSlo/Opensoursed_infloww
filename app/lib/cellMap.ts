"use client";

import { useEffect, useSyncExternalStore } from "react";

import { cellMode } from "@/lib/cellFlag";
import type { ListCaller } from "@/hooks/chatListLoadMore";
import { relay } from "@/lib/relay";
import {
  CELL_DEADLINE_MS, CELL_PAINT_MS, cellsReducer, cellToken, greyAccounts, groupByCell, INITIAL_CELLS, type Action,
  type CellMap, type CellsState,
} from "@/lib/cellInbox";

// Never persisted: a revoke bumps grant_gen, and a stale copy would key the inbox to the pre-revoke cache.
let map: CellMap | null = null;
let flight: Promise<CellMap> | null = null;
let cells: CellsState = INITIAL_CELLS;
let grey: ReadonlySet<string> = new Set();
let streamGrey: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();
const emit = () => { for (const l of listeners) l(); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
export const onCellMap = subscribe;

export function loadCellMap(): Promise<CellMap> {
  if (map) return Promise.resolve(map);
  flight ??= relay.get<CellMap>("/auth/cells").then((m) => {
    map = m;
    flight = null;
    emit();
    return m;
  }, (e: unknown) => {
    flight = null;
    throw e;
  });
  return flight;
}

export function currentCellMap(): CellMap | null {
  return map;
}

export function forgetCellMap(): void {
  map = null;
  flight = null;
  cells = INITIAL_CELLS;
  grey = new Set();
  streamGrey = new Set();
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
  const g = new Set([...greyAccounts(cells), ...streamGrey]);
  if (g.size === grey.size && [...g].every((id) => grey.has(id))) return false;
  grey = g;
  return true;
}

function dispatch(a: Action): void {
  const next = cellsReducer(cells, a);
  if (next === cells) return;
  cells = next;
  regrey();
  emit();
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
): Promise<CellResult<T>[]> {
  const scope = cellToken(m);
  return Promise.all(groupByCell(accounts, m).map(async ([cell, ids]): Promise<CellResult<T>> => {
    dispatch({ type: "ask", scope, cell, accounts: ids });
    const timer = AbortSignal.timeout(CELL_PAINT_MS);
    const signal = outer ? AbortSignal.any([outer, timer]) : timer;
    try {
      const { value, partial } = await run({ cell, accounts: ids, signal });
      dispatch({ type: "answered", scope, cell, partial });
      return { cell, accounts: ids, ok: true, value, partial };
    } catch (e) {
      if (outer?.aborted) throw e;
      dispatch({ type: timer.aborted || (e as Error)?.name === "TimeoutError" ? "timedOut" : "failed", scope, cell });
      return { cell, accounts: ids, ok: false };
    }
  }));
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
